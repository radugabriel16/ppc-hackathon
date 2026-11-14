from datetime import datetime

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select, text

from app.auth.dependencies import get_current_user
from app.models.enums import UserRole


def historical_access(
    include_historical: bool = Query(default=False, alias="includeHistorical"),
    user=Depends(get_current_user),
):
    if include_historical and user.role != UserRole.MANAGER:
        raise HTTPException(403, "Only a MANAGER can include historical issues")
    return include_historical


def validate_dates(start: datetime | None, end: datetime | None):
    if start and end and start >= end:
        raise HTTPException(422, "from must precede to (exclusive)")


def locate(db, location, region_id=None, segment_id=None):
    from app.models.geography import Subregion

    lon, lat = location.coordinates
    params = {"lon": lon, "lat": lat, "region": region_id, "segment": segment_id}
    if not db.scalar(text("""
        SELECT ST_Covers(geometry,ST_SetSRID(ST_Point(:lon,:lat),4326))
        FROM national_boundaries WHERE code='RO'
    """), params):
        raise HTTPException(422, "Issue point is outside Romania")
    # Validate explicit scope with ST_Covers even on a shared boundary.
    if segment_id is not None:
        segment = db.scalar(select(Subregion).where(
            Subregion.id == segment_id,
            text("ST_Covers(subregions.geometry,ST_SetSRID(ST_Point(:lon,:lat),4326))"),
        ).params(lon=lon, lat=lat))
        if segment is None or (region_id is not None and segment.region_id != region_id):
            raise HTTPException(422, "Issue point is outside the requested region/segment scope")
    elif region_id is not None and not db.scalar(text("""
        SELECT ST_Covers(geometry,ST_SetSRID(ST_Point(:lon,:lat),4326))
        FROM regions WHERE id=:region
    """), params):
        raise HTTPException(422, "Issue point is outside the requested region scope")
    derived = db.execute(text("""
        SELECT id,region_id,name FROM subregions
        WHERE ST_Covers(geometry,ST_SetSRID(ST_Point(:lon,:lat),4326))
        ORDER BY code LIMIT 1
    """), params).one_or_none()
    if derived is None:
        raise HTTPException(422, "Issue point is outside the operational regions")
    if region_id is not None and derived.region_id != region_id:
        raise HTTPException(422, "Boundary point belongs to the first covering region by segment code")
    # Boundary ties must use the same deterministic rule as the DB trigger.
    if segment_id is not None and derived.id != segment_id:
        raise HTTPException(422, "Boundary point belongs to the first covering segment by code")
    return derived
