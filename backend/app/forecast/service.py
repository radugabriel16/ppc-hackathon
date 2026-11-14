from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from filegrid_forecast.core import History
from filegrid_forecast.service import ForecastService

logger = logging.getLogger(__name__)
TRAINING_CUTOFF = date(2026, 5, 14)

METERS = """
SELECT m.id::text, m.external_code, c.client_type::text,
       a.id::text AS segment_id, a.code AS segment, r.code AS region
FROM meters m JOIN network_assets a ON a.id = m.asset_id
JOIN regions r ON r.id = a.region_id LEFT JOIN clients c ON c.id = m.client_id
WHERE a.id = :segment ORDER BY m.id
"""

# Missing, duplicate, overlapping, late or crossing intervals never become zero energy.
READINGS = """
WITH source AS (
    SELECT mr.*, date_bin('6 hours', mr.interval_start, TIMESTAMPTZ '2000-01-01')
           AS slot
    FROM meter_readings mr JOIN meters m ON m.id = mr.meter_id
    WHERE m.asset_id = :segment AND mr.interval_start >= :start
      AND mr.interval_start < :end
), ordered AS (
    SELECT *, lag(interval_end) OVER (
        PARTITION BY meter_id, slot ORDER BY interval_start, id
    ) AS previous_end FROM source
)
SELECT meter_id::text, slot AS interval_start, slot + INTERVAL '6 hours' AS interval_end,
       sum(energy_kwh)::float8 AS energy_kwh, max(received_at) AS received_at
FROM ordered GROUP BY meter_id, slot
HAVING min(interval_start) = slot AND max(interval_end) = slot + INTERVAL '6 hours'
   AND sum(extract(epoch FROM interval_end - interval_start)) = 21600
   AND bool_and(previous_end IS NULL OR previous_end = interval_start)
   AND bool_and(received_at >= interval_end AND received_at <= :cutoff)
   AND bool_and(energy_kwh >= 0 AND energy_kwh::text NOT IN ('NaN','Infinity','-Infinity'))
ORDER BY meter_id, slot
"""


def load_model(directory: Path | None = None) -> tuple[ForecastService | None, str | None]:
    directory = directory or Path(str(files("filegrid_forecast")))
    try:
        expected = json.loads((directory / "checksums.json").read_text())[
            "model/forecast_3d.joblib"
        ]
        artifact = directory / "model/forecast_3d.joblib"
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
            raise ValueError("model SHA-256 does not match checksums.json")
        return ForecastService(artifact), None
    except (OSError, ValueError, KeyError, RuntimeError, EOFError) as exc:
        logger.error("Forecast model unavailable: %s", exc)
        return None, f"Forecast model unavailable: {exc}"


def predict(service: ForecastService, history: History, segment: str) -> dict:
    # Missing client types are not silently reclassified as residential.
    known_types = history.meters.client_type.isin(
        ["RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL"]
    ).to_numpy()
    slots = history.slots.copy()
    slots[:, ~known_types, :] = np.nan
    for index in range(len(history.meters)):
        days = np.flatnonzero(np.isfinite(history.slots[:, index, :]).any(axis=1))
        if not len(days) or len(history.slots) - days[0] < 28:
            slots[:, index, :] = np.nan
    model_history = History(
        history.meters, history.start, history.end, slots, history.arrival
    )
    result = service.predict_segment(
        model_history, segment, include_meters=True, expected_meters=len(history.meters)
    )
    observed = history.snapshot(history.end)
    result["fallbackUsed"] = False
    for meter in result["meters"]:
        index = history.meters.index[history.meters.id == meter["meterId"]][0]
        recent = observed[-28:, index]
        recent = recent[np.isfinite(recent)][-7:]
        for point in meter["forecasts"]:
            point["fallbackUsed"] = point["status"] != "READY"
            point["fallbackReason"] = (
                "INSUFFICIENT_HISTORY" if known_types[index] else "MISSING_CLIENT_TYPE"
            ) if point["fallbackUsed"] else None
            if point["fallbackUsed"]:
                result["fallbackUsed"] = True
                point.update(
                    predictedEnergyKwh=round(float(recent.mean()), 6) if len(recent) else None,
                    referenceEnergyKwh=None, changeVsPreviousDayPct=None,
                    changeVsReferencePct=None, annualReferenceUsed=False,
                    status="READY" if len(recent) else "INSUFFICIENT_DATA",
                )
    for index, point in enumerate(result["forecasts"]):
        meters = [meter["forecasts"][index] for meter in result["meters"]]
        complete = all(m["status"] == "READY" for m in meters)
        fallback = any(m["fallbackUsed"] for m in meters)
        point["fallbackUsed"] = fallback
        if fallback:
            point.update(
                predictedEnergyKwh=round(sum(m["predictedEnergyKwh"] for m in meters), 6)
                if complete else None,
                eligibleMeters=sum(m["status"] == "READY" for m in meters),
                status="READY" if complete else "INSUFFICIENT_DATA",
                referenceEnergyKwh=None, changeVsReferencePct=None,
            )
    if result["fallbackUsed"]:
        result["method"] = "hgb_smooth_with_baseline_recent_daily_mean"
    result["dataSource"] = "CATALOG_METER_READINGS"
    result["generatedAt"] = datetime.now(timezone.utc).isoformat()
    return result


class ForecastRuntime:
    def __init__(self, directory: Path | None = None):
        self.service, self.error = load_model(directory)
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple[str, date], tuple[float, dict]] = OrderedDict()

    def get(self, db: Session, segment: str, origin: date) -> dict:
        if self.service is None:
            raise HTTPException(503, {
                "code": "FORECAST_UNAVAILABLE",
                "message": self.error or "Forecast model unavailable",
            }, headers={"Retry-After": "300"})
        key = (segment, origin)
        # Sync FastAPI handlers run in its threadpool; serialize the shared estimator
        # and bound both cache memory and duplicate concurrent predictions.
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                self.cache.move_to_end(key)
                return cached[1]
            meters = pd.DataFrame(db.execute(
                text(METERS), {"segment": segment}
            ).mappings().all(), columns=[
                "id", "external_code", "client_type", "segment_id", "segment", "region",
            ])
            if meters.empty:
                raise HTTPException(503, {
                    "code": "FORECAST_NO_METERS", "message": "No registered meters for this segment",
                })
            end = pd.Timestamp(origin, tz="UTC")
            start = end - pd.Timedelta(days=730)
            readings = pd.DataFrame(db.execute(text(READINGS), {
                "segment": segment, "start": start.to_pydatetime(),
                "end": end.to_pydatetime(),
                "cutoff": (end + pd.Timedelta(minutes=10)).to_pydatetime(),
            }).mappings().all(), columns=[
                "meter_id", "interval_start", "interval_end", "energy_kwh", "received_at",
            ])
            history = History.from_frames(meters, readings, start, end)
            result = predict(self.service, history, segment)
            self.cache[key] = (time.monotonic(), result)
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return result


def validate_origin(origin: date | None) -> date:
    now = datetime.now(timezone.utc)
    latest = (now - timedelta(minutes=10)).date()
    origin = origin or latest
    if not TRAINING_CUTOFF <= origin <= latest:
        raise HTTPException(422, "origin must be on/after 2026-05-14 and its 00:10 UTC cutoff must have passed")
    return origin
