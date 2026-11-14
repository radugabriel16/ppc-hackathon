import io
import logging
import time
import uuid
from datetime import datetime, timezone

import anyio
from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.metrics import FILE_TIME_TO_AVAILABLE_SECONDS
from app.metering.schemas import MeterReadingIngest, MeterReadingResource
from app.models.enums import FileCategory, FileStatus, StorageBackend
from app.models.files import File
from app.models.geography import NetworkAsset
from app.models.metering import Meter, MeterReading
from app.policies.service import PolicyManager
from app.storage.base import StorageNotFound, StorageUnavailable

logger = logging.getLogger("app.metering")
CATEGORY = FileCategory.METER_READING


def existing_reading(
    db: Session, meter_id: uuid.UUID, reading_key: str, digest: str,
) -> MeterReadingResource | None:
    row = db.execute(
        select(MeterReading, File.sha256)
        .join(File, MeterReading.file_id == File.id)
        .where(MeterReading.meter_id == meter_id, MeterReading.reading_key == reading_key)
    ).one_or_none()
    if row is None:
        return None
    if row.sha256 != digest:
        raise HTTPException(
            409, {"code": "READING_CONFLICT", "message": "Reading key has a different payload"}
        )
    return MeterReadingResource.model_validate(row.MeterReading)


async def ingest_reading(
    reading: MeterReadingIngest, content: bytes, digest: str,
    manager: PolicyManager, db: Session,
) -> tuple[MeterReadingResource, bool]:
    started = time.monotonic()

    def lookup():
        try:
            meter_id = db.scalar(select(Meter.id).where(
                Meter.external_code == reading.meter_external_code
            ))
            if meter_id is None:
                raise HTTPException(422, "Unknown meterExternalCode")
            return meter_id, existing_reading(db, meter_id, reading.reading_key, digest)
        finally:
            db.rollback()

    meter_id, existing = await anyio.to_thread.run_sync(lookup)
    if existing is not None:
        return existing, False

    file_id = uuid.uuid4()
    storage = manager.storages[StorageBackend.db]
    retained = False

    def persist(locator: str) -> tuple[MeterReadingResource, bool]:
        try:
            # Resolve and lock the current region after the storage write, not during it.
            region_id = db.scalar(
                select(NetworkAsset.region_id).join(Meter, Meter.asset_id == NetworkAsset.id)
                .where(Meter.id == meter_id).with_for_update(read=True, of=(Meter, NetworkAsset))
            )
            if region_id is None:
                raise HTTPException(422, "Meter no longer exists")
            now = datetime.now(timezone.utc)
            db.add(File(
                id=file_id, region_id=region_id, category=CATEGORY,
                original_name=f"{file_id}.json", media_type="application/json",
                size_bytes=len(content), sha256=digest, storage_backend=StorageBackend.db,
                storage_locator=locator, fallback_used=False, encrypted=False,
                status=FileStatus.READY, created_at=now, ready_at=now,
            ))
            db.flush()
            row = MeterReading(
                meter_id=meter_id, reading_key=reading.reading_key, seq=reading.seq,
                interval_start=reading.interval_start, interval_end=reading.interval_end,
                energy_kwh=reading.energy_kwh, file_id=file_id, received_at=now,
            )
            db.add(row)
            db.flush()
            resource = MeterReadingResource.model_validate(row)
            db.commit()
            return resource, True
        except IntegrityError as exc:
            db.rollback()
            if not (
                isinstance(exc.orig, UniqueViolation)
                and exc.orig.diag.constraint_name == "uq_meter_readings_meter_reading_key"
            ):
                raise
            try:
                winner = existing_reading(db, meter_id, reading.reading_key, digest)
                if winner is None:
                    raise
                return winner, False
            finally:
                db.rollback()

    async def discard_unreferenced() -> None:
        def referenced():
            try:
                db.rollback()
                return db.get(File, file_id) is not None
            finally:
                db.rollback()

        try:
            if not await anyio.to_thread.run_sync(referenced):
                await storage.delete(CATEGORY, str(file_id))
        except (SQLAlchemyError, StorageUnavailable, StorageNotFound):
            # Never delete bytes when a failed/ambiguous catalog commit cannot be checked.
            logger.warning("Meter ingest cleanup incomplete file_id=%s", file_id)

    try:
        with io.BytesIO(content) as stream:
            try:
                stored = await storage.put(CATEGORY, str(file_id), stream, len(content))
            except StorageUnavailable as exc:
                raise manager._unavailable() from exc
        resource, retained = await anyio.to_thread.run_sync(persist, stored.locator)
        if retained:
            FILE_TIME_TO_AVAILABLE_SECONDS.labels(category=CATEGORY.value).observe(
                time.monotonic() - started
            )
        return resource, retained
    finally:
        if not retained:
            with anyio.CancelScope(shield=True):
                await discard_unreferenced()
