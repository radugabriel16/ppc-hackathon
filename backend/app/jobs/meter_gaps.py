import math
from datetime import timedelta

import anyio
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.metrics import METER_READINGS_MISSING
from app.core.settings import get_settings
from app.jobs.scheduling import job_run
from app.models.geography import NetworkAsset, Region
from app.models.maintenance import MeterGap, WorkerState
from app.models.metering import Meter, MeterReading
from app.uploads.service import now


def count_gaps(readings) -> int:
    missing = 0
    for previous, current in zip(readings, readings[1:]):
        seq_gap = max(0, current.seq - previous.seq - 1)
        cadence = (previous.interval_end - previous.interval_start).total_seconds()
        interval_gap = max(0, math.ceil(
            (current.interval_start - previous.interval_end).total_seconds() / cadence
        ))
        # A sequence and interval gap describe the same lost readings.
        missing += max(seq_gap, interval_gap)
    return missing


def sample_meter_gaps() -> None:
    settings = get_settings()
    checked_at = now()
    active_since = checked_at - timedelta(seconds=settings.meter_active_seconds)
    window = checked_at - timedelta(seconds=settings.meter_gap_window_seconds)
    with Session(get_catalog_engine()) as db:
        state = db.get(WorkerState, "meter_gap_cursor")
        if state is None:
            state = WorkerState(name="meter_gap_cursor")
            db.add(state)
        statement = select(Meter.id, NetworkAsset.region_id).join(
            NetworkAsset, NetworkAsset.id == Meter.asset_id
        ).order_by(Meter.id).limit(settings.worker_batch_size)
        if state.cursor is not None:
            statement = statement.where(Meter.id > state.cursor)
        meters = db.execute(statement).all()
        for meter_id, region_id in meters:
            readings = list(reversed(db.scalars(select(MeterReading).where(
                MeterReading.meter_id == meter_id,
                MeterReading.interval_end >= window,
                MeterReading.interval_end <= checked_at,
            ).order_by(MeterReading.interval_end.desc(), MeterReading.id.desc())
                .limit(settings.meter_gap_readings_limit)).all()))
            latest = max((row.received_at for row in readings), default=window)
            current_end = max((row.interval_end for row in readings), default=window)
            active_until = min(latest, current_end) + timedelta(seconds=settings.meter_active_seconds)
            missing = count_gaps(readings) if min(latest, current_end) >= active_since else 0
            db.merge(MeterGap(
                meter_id=meter_id, region_id=region_id,
                missing=missing, active_until=active_until,
            ))
        state.cursor = meters[-1].id if len(meters) == settings.worker_batch_size else None
        db.commit()


def expose_meter_gaps() -> None:
    with Session(get_catalog_engine()) as db:
        rows = db.execute(select(
            Region.code,
            func.coalesce(func.sum(MeterGap.missing).filter(MeterGap.active_until > now()), 0),
        ).outerjoin(MeterGap, MeterGap.region_id == Region.id).group_by(Region.code)).all()
    for region, missing in rows:
        METER_READINGS_MISSING.labels(region=region).set(missing)


async def detect_meter_gaps() -> None:
    async with job_run("meter_gaps", 5) as run:
        if run:
            await anyio.to_thread.run_sync(sample_meter_gaps)
    # Every replica exports the shared snapshot, including explicit zeroes.
    await anyio.to_thread.run_sync(expose_meter_gaps)
