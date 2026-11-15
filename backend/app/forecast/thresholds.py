"""Observed-only daily capacity defaults; explicit manager overrides are preserved."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.forecast.service import READINGS
from app.models.forecast import SegmentThreshold
from app.history.readings import complete_readings
import numpy as np

THRESHOLD_MULTIPLIER = 1.03
DAILY_HISTORY = f"""
WITH slots AS ({READINGS.replace("m.asset_id = :segment", "m.subregion_id = :segment")}),
daily AS (
    SELECT date_trunc('day', interval_start AT TIME ZONE 'UTC') AS day,
           sum(energy_kwh) AS energy
    FROM slots GROUP BY 1
    HAVING count(*) = 4 * (SELECT count(*) FROM meters WHERE subregion_id=:segment)
)
SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY energy) AS p95,
       count(*) AS days FROM daily
"""


def calibrate_threshold(db, segment_id, as_of: datetime):
    existing = db.get(SegmentThreshold, segment_id)
    if existing is not None and existing.source == "MANUAL":
        return existing
    end = as_of.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=28)
    slots = complete_readings(db, segment_id, start, end, as_of, subregion=True)
    expected = db.scalar(text("SELECT count(*) FROM meters WHERE subregion_id=:id"),
                         {"id": segment_id})
    daily = {}
    for slot in slots:
        daily.setdefault(slot["interval_start"].date(), []).append(slot["energy_kwh"])
    totals = [sum(values) for values in daily.values() if len(values) == 4 * expected]
    days = len(totals)
    p95 = float(np.percentile(totals, 95)) if totals else None
    if days < 14 or p95 is None or p95 <= 0:
        raise HTTPException(503, f"Threshold calibration needs 14 complete segment days: {segment_id}")
    values = {
        "segment_id": segment_id, "daily_energy_kwh": round(float(p95) * THRESHOLD_MULTIPLIER, 6),
        "source": "HISTORY_P95",
        "calibration": {
            "startInclusive": start.date().isoformat(), "endExclusive": end.date().isoformat(),
            "sampleDays": days, "percentile": 95, "multiplier": THRESHOLD_MULTIPLIER,
            "p95Kwh": float(p95), "asOf": as_of.isoformat(),
        },
    }
    db.execute(insert(SegmentThreshold).values(**values).on_conflict_do_update(
        index_elements=[SegmentThreshold.segment_id],
        set_={key: value for key, value in values.items() if key != "segment_id"},
        where=SegmentThreshold.source != "MANUAL",
    ))
    if existing is not None:
        db.expire(existing)
    return db.get(SegmentThreshold, segment_id)


def threshold_for_run(db, segment_id, as_of):
    config = db.get(SegmentThreshold, segment_id)
    if config is None or config.source == "UNCONFIGURED" or (
        config.source == "HISTORY_P95"
        and config.calibration["endExclusive"] != as_of.astimezone(timezone.utc).date().isoformat()
    ):
        config = calibrate_threshold(db, segment_id, as_of)
    return config
