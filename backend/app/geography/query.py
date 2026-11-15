"""Validated, additive spatial and scope filters for bounded map queries."""
import math
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query
from sqlalchemy import func


def bounding_box(bbox: str | None = Query(default=None)):
    if bbox is None:
        return None
    try:
        values = tuple(float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(422, "bbox must be west,south,east,north in WGS84") from exc
    if len(values) != 4 or not all(math.isfinite(v) for v in values):
        raise HTTPException(422, "bbox must contain four finite coordinates")
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(422, "bbox must have west<east, south<north and valid WGS84 coordinates")
    return func.ST_MakeEnvelope(west, south, east, north, 4326)


def validate_scope(scope: Literal["country", "region", "segment"] | None,
                   region: UUID | None, segment: UUID | None):
    if scope == "country" and (region or segment):
        raise HTTPException(422, "country scope does not accept regionId or segmentId")
    if scope == "region" and (region is None or segment is not None):
        raise HTTPException(422, "region scope requires only regionId")
    if scope == "segment" and segment is None:
        raise HTTPException(422, "segment scope requires segmentId or subregionId")


def feature_page(rows, page, size):
    return {
        "type": "FeatureCollection", "features": rows[:size],
        "page": page, "size": size, "hasMore": len(rows) > size,
    }
