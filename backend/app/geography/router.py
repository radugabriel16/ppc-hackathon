import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.api import Pagination, paginate
from app.core.db import get_catalog_db
from app.geography.schemas import AssetResource, MeterResource, RegionResource
from app.geography.service import issue_region_filter, point_geojson, region_filter
from app.issues.service import historical_access
from app.models.geography import NetworkAsset, Region, Subregion
from app.models.issues import MapIssue
from app.models.metering import Meter
from app.models.outages import Outage
from app.geography.query import bounding_box, feature_page, validate_scope

router = APIRouter(
    prefix="/api/v1", tags=["geography"], dependencies=[Depends(get_current_user)]
)


@router.get("/boundaries/romania")
def romania_boundary(db: Session = Depends(get_catalog_db)):
    geometry = db.scalar(text("SELECT ST_AsGeoJSON(geometry) FROM national_boundaries WHERE code='RO'"))
    if geometry is None:
        raise HTTPException(503, "Romania boundary is unavailable")
    return json.loads(geometry)


@router.get("/regions")
def list_regions(pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db)):
    statement = select(
        Region.id, Region.code, Region.name, func.ST_AsGeoJSON(Region.center).label("center"),
        Region.bounds,
        func.ST_AsGeoJSON(func.ST_Multi(func.ST_SimplifyPreserveTopology(Region.geometry, 0.001))).label("geometry"),
    ).order_by(Region.code)
    result = paginate(db, statement, pagination, RegionResource, mappings=True)
    for region in result["items"]:
        region.subregions = [
            {
                "id": str(s.id), "parentId": str(s.region_id), "code": s.code, "name": s.name,
                "geometry": json.loads(geometry), "meterCount": count,
            }
            for s, geometry, count in db.execute(
                select(
                    Subregion,
                    func.ST_AsGeoJSON(func.ST_Multi(func.ST_SimplifyPreserveTopology(Subregion.geometry, 0.001))),
                    select(func.count()).select_from(Meter)
                    .where(Meter.subregion_id == Subregion.id).correlate(Subregion).scalar_subquery(),
                ).where(Subregion.region_id == region.id).order_by(Subregion.code)
            )
        ]
        region.meter_count = sum(s["meterCount"] for s in region.subregions)
    return result


@router.get("/assets")
def list_assets(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(NetworkAsset)
    if region_id is not None:
        statement = statement.where(region_filter(NetworkAsset, region_id))
    if subregion_id is not None:
        statement = statement.where(NetworkAsset.subregion_id == subregion_id)
    return paginate(db, statement.order_by(NetworkAsset.code), pagination, AssetResource)


@router.get("/meters")
def list_meters(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    segment_id: Annotated[UUID | None, Query(alias="segmentId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(
        Meter.id, Meter.external_code, Meter.asset_id, Meter.client_id,
        Meter.subregion_id, Meter.subregion_id.label("segment_id"),
        NetworkAsset.region_id,
        point_geojson(Meter.location).label("location"),
    ).join(NetworkAsset, Meter.asset_id == NetworkAsset.id)
    if region_id is not None:
        statement = statement.where(region_filter(NetworkAsset, region_id))
    if subregion_id is not None:
        statement = statement.where(Meter.subregion_id == subregion_id)
    if segment_id is not None:
        statement = statement.where(Meter.subregion_id == segment_id)
    return paginate(db, statement.order_by(Meter.external_code), pagination, MeterResource, mappings=True)


@router.get("/map/features")
def map_features(
    layer: Literal["ASSETS", "ISSUES", "OUTAGES", "REGIONS", "SUBREGIONS"],
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    segment_id: Annotated[UUID | None, Query(alias="segmentId")] = None,
    include_historical: bool = Depends(historical_access),
    bbox=Depends(bounding_box),
    scope: Literal["country", "region", "segment"] | None = None,
    page: int = Query(default=0, ge=0),
    size: int = Query(default=1000, ge=1, le=2000),
    db: Session = Depends(get_catalog_db),
):
    validate_scope(scope, region_id, segment_id or subregion_id)
    if layer in ("REGIONS", "SUBREGIONS"):
        model = Region if layer == "REGIONS" else Subregion
        statement = select(
            model, func.ST_AsGeoJSON(func.ST_Multi(func.ST_SimplifyPreserveTopology(model.geometry, 0.001))),
        ).where(model.geometry.is_not(None)).order_by(model.code)
        if region_id is not None:
            column = Region.id if model is Region else Subregion.region_id
            statement = statement.where(column == region_id)
        if subregion_id is not None:
            if model is Region:
                statement = statement.where(Region.id == select(Subregion.region_id)
                                            .where(Subregion.id == subregion_id).scalar_subquery())
            else:
                statement = statement.where(Subregion.id == subregion_id)
        if segment_id is not None:
            column = Subregion.id if model is Subregion else Region.id
            value = segment_id if model is Subregion else select(Subregion.region_id).where(
                Subregion.id == segment_id,
            ).scalar_subquery()
            statement = statement.where(column == value)
        if bbox is not None:
            statement = statement.where(func.ST_Intersects(model.geometry, bbox))
        return feature_page([
                {"type": "Feature", "id": str(area.id), "geometry": json.loads(geometry),
                 "properties": {
                     "id": str(area.id), "code": area.code, "name": area.name,
                     "parentId": str(area.region_id) if model is Subregion else None,
                 }}
                for area, geometry in db.execute(statement.offset(page*size).limit(size+1))
            ], page, size)
    if layer == "ASSETS":
        properties = func.json_build_object(
            "id", NetworkAsset.id, "kind", "ASSET", "assetType", NetworkAsset.type,
            "code", NetworkAsset.code, "name", NetworkAsset.name,
        )
        statement = select(
            func.ST_AsGeoJSON(NetworkAsset.geometry), properties
        ).order_by(NetworkAsset.id)
    elif layer == "ISSUES":
        properties = func.json_build_object(
            "id", MapIssue.id, "kind", "ISSUE", "assetId", MapIssue.asset_id,
            "severity", MapIssue.severity, "status", MapIssue.status,
            "version", MapIssue.version,
            "type", MapIssue.type, "title", MapIssue.title,
            "regionId", MapIssue.region_id, "segmentId", MapIssue.subregion_id,
        )
        statement = (
            select(point_geojson(MapIssue.location), properties)
            .join(NetworkAsset, MapIssue.asset_id == NetworkAsset.id)
            .order_by(MapIssue.id)
        )
        if not include_historical:
            statement = statement.where(MapIssue.is_historical.is_(False))
    else:
        properties = func.json_build_object(
            "id", Outage.id, "kind", "OUTAGE", "assetId", Outage.asset_id,
            "severity", Outage.severity, "startedAt", Outage.started_at, "endedAt", Outage.ended_at,
        )
        statement = (
            select(func.ST_AsGeoJSON(NetworkAsset.geometry), properties)
            .join(NetworkAsset, Outage.asset_id == NetworkAsset.id)
            .order_by(Outage.id)
        )
    if region_id is not None:
        statement = statement.where(
            issue_region_filter(region_id) if layer == "ISSUES"
            else region_filter(NetworkAsset, region_id)
        )
    if subregion_id is not None:
        column = MapIssue.subregion_id if layer == "ISSUES" else NetworkAsset.subregion_id
        statement = statement.where(column == subregion_id)
    if segment_id is not None:
        column = MapIssue.subregion_id if layer == "ISSUES" else NetworkAsset.subregion_id
        statement = statement.where(column == segment_id)
    if bbox is not None:
        geometry_column = MapIssue.location if layer == "ISSUES" else NetworkAsset.geometry
        statement = statement.where(func.ST_Intersects(geometry_column, bbox))
    return feature_page([
            {"type": "Feature",
             "geometry": geometry if isinstance(geometry, dict) else json.loads(geometry),
             "properties": properties}
            for geometry, properties in db.execute(statement.offset(page*size).limit(size+1))
        ], page, size)
