from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.api import Pagination
from app.core.db import get_catalog_db
from app.forecast.service import validate_origin
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1", tags=["stats"])


def forecast_user(user=Depends(get_current_user)):
    # As with other catalog reads, both application roles have access to all regions.
    if user.role not in (UserRole.OPERATOR, UserRole.MANAGER):
        raise HTTPException(403, "Insufficient permissions")
    return user


@router.get("/segments/{segment_id}/forecast", dependencies=[Depends(forecast_user)])
def segment_forecast(
    segment_id: UUID, request: Request,
    origin: date | None = None,
    include_meters: Annotated[bool, Query(alias="includeMeters")] = False,
    db: Session = Depends(get_catalog_db),
):
    origin = validate_origin(origin)
    if not db.scalar(text("SELECT 1 FROM network_assets WHERE id = :id"), {"id": segment_id}):
        raise HTTPException(404, "Segment not found")
    result = request.app.state.forecast.get(db, str(segment_id), origin)
    return result if include_meters else {k: v for k, v in result.items() if k != "meters"}


@router.get("/meters/{meter_id}/forecast", dependencies=[Depends(forecast_user)])
def meter_forecast(
    meter_id: UUID, request: Request, origin: date | None = None,
    db: Session = Depends(get_catalog_db),
):
    origin = validate_origin(origin)
    segment = db.scalar(text("SELECT asset_id FROM meters WHERE id = :id"), {"id": meter_id})
    if segment is None:
        raise HTTPException(404, "Meter not found")
    result = request.app.state.forecast.get(db, str(segment), origin)
    meter = next(m for m in result["meters"] if m["meterId"] == str(meter_id))
    return {
        **{k: v for k, v in result.items() if k not in ("meters", "forecasts")},
        **meter, "fallbackUsed": any(p["fallbackUsed"] for p in meter["forecasts"]),
    }


@router.get("/stats/forecast", dependencies=[Depends(forecast_user)])
def forecasts(
    request: Request,
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    origin: date | None = None, pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    origin = validate_origin(origin)
    params = {"region": region_id}
    sql = """FROM network_assets a WHERE
        (CAST(:region AS uuid) IS NULL OR a.region_id = :region)
        AND EXISTS (SELECT 1 FROM meters m WHERE m.asset_id = a.id)"""
    total = db.scalar(text("SELECT count(*) " + sql), params)
    segments = db.scalars(text("SELECT a.id " + sql + " ORDER BY a.code, a.id LIMIT :limit OFFSET :offset"),
                          {**params, "limit": pagination.size, "offset": pagination.page * pagination.size})
    items = []
    for segment in segments.all():
        result = request.app.state.forecast.get(db, str(segment), origin)
        items.append({k: v for k, v in result.items() if k != "meters"})
    return {
        "items": items, "page": pagination.page, "size": pagination.size,
        "totalElements": total, "totalPages": (total + pagination.size - 1) // pagination.size,
    }
