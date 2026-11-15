"""Issue creation and version-checked transitions with transactional audit."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from typing import Annotated
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_catalog_db
from app.core.api import Pagination
from app.geography.service import issue_region_filter, point_geojson
from app.core.logging import get_request_id
from app.issues.schemas import IssueCreate, IssueResource, IssueStatusUpdate
from app.issues.service import historical_access, locate, validate_dates
from app.models.audit import AuditEvent
from app.models.auth import AppUser
from app.models.enums import FileCategory, FileStatus, IssueStatus, IssueType, UserRole
from app.models.files import File
from app.models.clients import Client
from app.models.metering import Meter
from app.models.geography import NetworkAsset
from app.models.inspections import VideoInspection
from app.models.issues import MapIssue

router = APIRouter(prefix="/api/v1", tags=["map-issues"])


@router.get("/stats/issues")
def issue_stats(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    segment_id: Annotated[UUID | None, Query(alias="segmentId")] = None,
    include_historical: bool = Depends(historical_access),
    db: Session = Depends(get_catalog_db),
):
    statement = select(MapIssue.type, MapIssue.status, func.count()).group_by(
        MapIssue.type, MapIssue.status,
    )
    if not include_historical:
        statement = statement.where(MapIssue.is_historical.is_(False))
    if region_id:
        statement = statement.where(MapIssue.region_id == region_id)
    if segment_id:
        statement = statement.where(MapIssue.subregion_id == segment_id)
    return {"items": [
        {"type": kind, "status": status, "count": count}
        for kind, status, count in db.execute(statement.order_by(MapIssue.type, MapIssue.status))
    ]}


@router.get("/map-issues", dependencies=[Depends(get_current_user)])
def list_issues(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    segment_id: Annotated[UUID | None, Query(alias="segmentId")] = None,
    type: IssueType | None = None, status: IssueStatus | None = None,
    client_id: Annotated[UUID | None, Query(alias="clientId")] = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    include_historical: bool = Depends(historical_access),
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    validate_dates(from_time, to_time)
    statement = select(MapIssue, point_geojson(MapIssue.location)).join(
        NetworkAsset, NetworkAsset.id == MapIssue.asset_id,
    )
    if not include_historical:
        statement = statement.where(MapIssue.is_historical.is_(False))
    if region_id is not None:
        statement = statement.where(issue_region_filter(region_id))
    if subregion_id is not None:
        statement = statement.where(MapIssue.subregion_id == subregion_id)
    for column, value in (
        (MapIssue.subregion_id, segment_id), (MapIssue.type, type),
        (MapIssue.status, status), (MapIssue.client_id, client_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if from_time:
        statement = statement.where(MapIssue.created_at >= from_time)
    if to_time:
        statement = statement.where(MapIssue.created_at < to_time)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(MapIssue.created_at.desc(), MapIssue.id)
                      .offset(pagination.page * pagination.size).limit(pagination.size))
    return {
        "items": [resource(db, row, location) for row, location in rows], "page": pagination.page,
        "size": pagination.size, "totalElements": total,
        "totalPages": (total + pagination.size - 1) // pagination.size,
    }


def resource(db: Session, issue: MapIssue, location=None) -> IssueResource:
    if location is None:
        location = db.scalar(
            select(point_geojson(MapIssue.location)).where(MapIssue.id == issue.id)
        )
    return IssueResource(
        **{
            field: getattr(issue, field)
            for field in IssueResource.model_fields if field not in ("location", "segment_id")
        },
        segment_id=issue.subregion_id,
        location=location,
    )


def audit(db: Session, issue: MapIssue, user: AppUser, action: str) -> None:
    db.add(AuditEvent(
        actor_id=user.id, action=action, entity_type="map_issue", entity_id=issue.id,
        occurred_at=datetime.now(timezone.utc), request_id=(get_request_id() or "")[:64] or None,
        details={
            "status": issue.status.value, "version": issue.version,
            "assignedTeamLabel": issue.assigned_team_label,
        },
    ))


@router.post("/map-issues", status_code=201, response_model=IssueResource)
def create_issue(
    body: IssueCreate, user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    return create_validated_issue(body, user, db)


def create_validated_issue(body: IssueCreate, user: AppUser, db: Session, issue_id: UUID | None = None):
    file = None
    upload_issue = body.type in (IssueType.DRONE_DETECTED, IssueType.OUTAGE_VIDEO) and body.file_id is not None
    if upload_issue:
        file = db.scalar(select(File).where(File.id == body.file_id).with_for_update())
        if file is None:
            raise HTTPException(422, "fileId does not identify an uploaded file")
        if file.placed_issue_id is not None:
            result = resource(db, db.get(MapIssue, file.placed_issue_id))
            db.commit()
            return result
        existing = db.scalar(select(MapIssue).where(
            MapIssue.file_id == file.id,
            MapIssue.type.in_((IssueType.DRONE_DETECTED, IssueType.OUTAGE_VIDEO)),
            MapIssue.is_historical.is_(False),
        ).order_by(MapIssue.created_at, MapIssue.id).limit(1))
        if existing is not None:
            file.placed_issue_id = existing.id
            result = resource(db, existing)
            db.commit()
            return result
    area = locate(db, body.location, body.region_id, body.segment_id or body.subregion_id)
    asset = db.get(NetworkAsset, body.asset_id) if body.asset_id else db.scalar(
        select(NetworkAsset).where(NetworkAsset.region_id == area.region_id).order_by(
            func.ST_Distance(
                NetworkAsset.geometry,
                func.ST_SetSRID(func.ST_Point(*body.location.coordinates), 4326),
            ), NetworkAsset.id,
        ).limit(1)
    )
    if asset is None:
        raise HTTPException(422, detail="assetId does not identify a network asset")
    if area.region_id != asset.region_id:
        raise HTTPException(422, "assetId must belong to the issue point's region")
    file_id = body.file_id
    if body.video_inspection_id is not None:
        video = db.get(VideoInspection, body.video_inspection_id)
        if video is None or video.asset_id != body.asset_id:
            raise HTTPException(422, detail="videoInspectionId must belong to assetId")
        if file_id is not None and file_id != video.file_id:
            raise HTTPException(422, "fileId must match videoInspectionId")
        file_id = video.file_id
    issue_type = body.type
    if body.video_inspection_id and issue_type == IssueType.OUTAGE_REPORT:
        issue_type = IssueType.DRONE_DETECTED
    if issue_type in (IssueType.OUTAGE_VIDEO, IssueType.DRONE_DETECTED) and file_id is None:
        raise HTTPException(422, "Video issues require an uploaded video")
    if file_id is not None:
        file = file or db.get(File, file_id)
        if file is None or file.status != FileStatus.READY or (
            not upload_issue and file.region_id != area.region_id
        ):
            raise HTTPException(422, "fileId must be READY and belong to the issue region")
        if issue_type in (IssueType.OUTAGE_VIDEO, IssueType.DRONE_DETECTED) and (
            file.category not in (
                (FileCategory.DRONE_VIDEO,) if issue_type == IssueType.DRONE_DETECTED
                else (FileCategory.OUTAGE_RECORD, FileCategory.DRONE_VIDEO)
            )
        ):
            raise HTTPException(422, "fileId must identify an uploaded video")
        if upload_issue and body.description is not None and len(body.description) > 1000:
            raise HTTPException(422, "Upload issue description must not exceed 1000 characters")
    client_id = body.client_id
    if body.meter_id:
        meter = db.get(Meter, body.meter_id)
        if meter is None or meter.subregion_id != area.id:
            raise HTTPException(422, "meterId must belong to the issue segment")
        if client_id and client_id != meter.client_id:
            raise HTTPException(422, "clientId must match meterId")
        client_id = client_id or meter.client_id
    if client_id:
        client = db.get(Client, client_id)
        if client is None or client.region_id != area.region_id:
            raise HTTPException(422, "clientId must belong to the issue region")
    label = {
        IssueType.OUTAGE_REPORT: "Outage report",
        IssueType.OUTAGE_VIDEO: "Video outage report",
        IssueType.DRONE_DETECTED: "Drone-detected issue",
    }[issue_type]
    lon, lat = body.location.coordinates
    issue = MapIssue(
        **({"id": issue_id} if issue_id is not None else {}),
        **body.model_dump(exclude={
            "location", "region_id", "segment_id", "subregion_id", "type",
            "file_id", "client_id", "description", "title", "captured_at", "asset_id",
        }),
        asset_id=asset.id,
        type=issue_type, title=body.title or f"{label}: {area.name}",
        description=(
            body.description if upload_issue
            else f"{label} in {area.name} at {lon:.6f}, {lat:.6f}."
            + (f" {body.description}" if body.description else "")
        ),
        region_id=area.region_id, file_id=file_id, client_id=client_id,
        location=WKTElement(f"POINT({lon} {lat})", srid=4326),
        created_by=user.id, created_at=datetime.now(timezone.utc),
        status=IssueStatus.OPEN, version=1,
    )
    db.add(issue)
    db.flush()
    if upload_issue:
        file.placed_issue_id = issue.id
        if body.captured_at is not None:
            file.captured_at = body.captured_at
        if body.description is not None:
            file.description = body.description
    db.refresh(issue, ["subregion_id"])
    result = resource(db, issue)
    audit(db, issue, user, "MAP_ISSUE_CREATED")
    db.commit()
    return result


@router.patch("/map-issues/{id}/status", response_model=IssueResource)
def update_issue_status(
    id: UUID, body: IssueStatusUpdate, user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    if body.status == IssueStatus.RESOLVED and user.role != UserRole.MANAGER:
        raise HTTPException(403, detail="Only a MANAGER can resolve map issues")
    changes = {
        "status": body.status, "version": MapIssue.version + 1,
        "resolved_at": datetime.now(timezone.utc) if body.status == IssueStatus.RESOLVED else None,
    }
    if "assigned_team_label" in body.model_fields_set:
        changes["assigned_team_label"] = body.assigned_team_label
    issue = db.scalar(
        update(MapIssue).where(MapIssue.id == id, MapIssue.version == body.version)
        .values(**changes).returning(MapIssue)
    )
    if issue is None:
        if db.get(MapIssue, id) is None:
            raise HTTPException(404, detail="Map issue not found")
        raise HTTPException(409, detail={
            "code": "VERSION_CONFLICT", "message": "Map issue version changed; reload and retry",
        })
    result = resource(db, issue)
    audit(db, issue, user, "MAP_ISSUE_STATUS_UPDATED")
    db.commit()
    return result
