"""Issue creation and version-checked transitions with transactional audit."""
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Annotated
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_catalog_db
from app.core.api import Pagination
from app.geography.service import issue_region_filter
from app.core.logging import get_request_id
from app.issues.schemas import IssueCreate, IssueResource, IssueStatusUpdate
from app.models.audit import AuditEvent
from app.models.auth import AppUser
from app.models.enums import IssueStatus, UserRole
from app.models.geography import NetworkAsset
from app.models.inspections import VideoInspection
from app.models.issues import MapIssue

router = APIRouter(prefix="/api/v1", tags=["map-issues"])


@router.get("/map-issues", dependencies=[Depends(get_current_user)])
def list_issues(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(MapIssue).join(NetworkAsset, NetworkAsset.id == MapIssue.asset_id)
    if region_id is not None:
        statement = statement.where(issue_region_filter(region_id))
    if subregion_id is not None:
        statement = statement.where(MapIssue.subregion_id == subregion_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.scalars(statement.order_by(MapIssue.created_at.desc(), MapIssue.id)
                      .offset(pagination.page * pagination.size).limit(pagination.size))
    return {
        "items": [resource(db, row) for row in rows], "page": pagination.page,
        "size": pagination.size, "totalElements": total,
        "totalPages": (total + pagination.size - 1) // pagination.size,
    }


def resource(db: Session, issue: MapIssue) -> IssueResource:
    location = db.scalar(
        select(func.ST_AsGeoJSON(MapIssue.location)).where(MapIssue.id == issue.id)
    )
    return IssueResource(
        **{
            field: getattr(issue, field)
            for field in IssueResource.model_fields if field != "location"
        },
        location=json.loads(location),
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
    if db.get(NetworkAsset, body.asset_id) is None:
        raise HTTPException(422, detail="assetId does not identify a network asset")
    if body.video_inspection_id is not None:
        video = db.get(VideoInspection, body.video_inspection_id)
        if video is None or video.asset_id != body.asset_id:
            raise HTTPException(422, detail="videoInspectionId must belong to assetId")
    lon, lat = body.location.coordinates
    issue = MapIssue(
        **body.model_dump(exclude={"location"}),
        location=WKTElement(f"POINT({lon} {lat})", srid=4326),
        created_by=user.id, created_at=datetime.now(timezone.utc),
        status=IssueStatus.OPEN, version=1,
    )
    db.add(issue)
    db.flush()
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
