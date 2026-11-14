import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.api import Pagination, paginate
from app.core.db import get_catalog_db
from app.geography.schemas import AssetResource, MeterResource, RegionResource
from app.models.geography import NetworkAsset, Region
from app.models.issues import MapIssue
from app.models.metering import Meter
from app.models.outages import Outage

router = APIRouter(
    prefix="/api/v1", tags=["geography"], dependencies=[Depends(get_current_user)]
)


@router.get("/regions")
def list_regions(pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db)):
    statement = select(
        Region.id, Region.code, Region.name, func.ST_AsGeoJSON(Region.center).label("center"),
        Region.bounds,
    ).order_by(Region.code)
    return paginate(db, statement, pagination, RegionResource, mappings=True)


@router.get("/assets")
def list_assets(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(NetworkAsset)
    if region_id is not None:
        statement = statement.where(NetworkAsset.region_id == region_id)
    return paginate(db, statement.order_by(NetworkAsset.code), pagination, AssetResource)


@router.get("/meters")
def list_meters(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(Meter).join(NetworkAsset, Meter.asset_id == NetworkAsset.id)
    if region_id is not None:
        statement = statement.where(NetworkAsset.region_id == region_id)
    return paginate(db, statement.order_by(Meter.external_code), pagination, MeterResource)


@router.get("/map/features")
def map_features(
    layer: Literal["ASSETS", "ISSUES", "OUTAGES"],
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    db: Session = Depends(get_catalog_db),
):
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
        )
        statement = (
            select(func.ST_AsGeoJSON(MapIssue.location), properties)
            .join(NetworkAsset, MapIssue.asset_id == NetworkAsset.id)
            .order_by(MapIssue.id)
        )
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
        statement = statement.where(NetworkAsset.region_id == region_id)
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": json.loads(geometry), "properties": properties}
            for geometry, properties in db.execute(statement)
        ],
    }
