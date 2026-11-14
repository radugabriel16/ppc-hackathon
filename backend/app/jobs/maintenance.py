import logging
from contextlib import aclosing
from datetime import timedelta
from uuid import UUID

import anyio
from fastapi import HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.metrics import FILE_TIME_TO_AVAILABLE_SECONDS
from app.core.settings import get_settings
from app.documents.encryption import DocumentKey, IntegrityError
from app.files.service import FileReader
from app.jobs.scheduling import job_run
from app.models.enums import FileStatus
from app.models.clients import ClientDocument
from app.models.files import File
from app.models.inspections import VideoInspection
from app.models.metering import MeterReading
from app.models.outages import Outage
from app.models.uploads import UploadSession
from app.policies.service import PolicyManager
from app.storage.base import StorageNotFound, StorageUnavailable
from app.uploads.locking import upload_lock
from app.uploads.service import ACTIVE_STATUSES, now

logger = logging.getLogger("app.jobs.maintenance")


async def integrity_scrub(manager: PolicyManager, key: DocumentKey) -> None:
    settings = get_settings()
    async with job_run("integrity_scrub", 5) as run:
        if not run:
            return

        def candidates():
            with Session(get_catalog_engine(), expire_on_commit=False) as db:
                return db.scalars(select(File).where(
                    File.status == FileStatus.READY,
                    or_(File.last_verified_at.is_(None), File.last_verified_at <= (
                        now() - timedelta(seconds=settings.integrity_scrub_interval_seconds)
                    )),
                    or_(File.maintenance_at.is_(None), File.maintenance_at <= (
                        now() - timedelta(seconds=settings.worker_retry_seconds)
                    )),
                ).order_by(
                    File.last_verified_at.asc().nullsfirst(),
                    File.maintenance_at.asc().nullsfirst(), File.id,
                ).limit(settings.worker_batch_size)).all()

        for file in await anyio.to_thread.run_sync(candidates):
            started = anyio.current_time()
            try:
                async with manager.acquire(file.category):
                    reader = FileReader(file, manager, key, None, None)
                    async with aclosing(reader.chunks()) as chunks:
                        async for _ in chunks:
                            pass
            except IntegrityError:
                logger.warning("Integrity scrub detected corrupt file file_id=%s", file.id)
            except HTTPException as exc:
                logger.warning("Integrity scrub deferred file_id=%s status=%s", file.id, exc.status_code)
            finally:
                def attempted():
                    with Session(get_catalog_engine()) as db:
                        current = db.get(File, file.id)
                        if current is not None:
                            current.maintenance_at = now()
                            db.commit()
                await anyio.to_thread.run_sync(attempted)
                # Pace whole-file reads without consuming the adapter's I/O deadline.
                await anyio.sleep(max(
                    0, file.size_bytes / settings.integrity_scrub_bytes_per_second
                    - (anyio.current_time() - started),
                ))


async def reconcile_files(manager: PolicyManager, key: DocumentKey) -> None:
    settings = get_settings()
    async with job_run("reconcile_files", 5) as run:
        if not run:
            return

        def candidates():
            with Session(get_catalog_engine()) as db:
                active_upload = exists().where(
                    UploadSession.file_id == File.id,
                    or_(
                        UploadSession.status.in_(ACTIVE_STATUSES),
                        UploadSession.s3_upload_id.is_not(None),
                    ),
                )
                return list(db.scalars(select(File.id).where(
                    File.status.in_((FileStatus.STAGING, FileStatus.VERIFYING, FileStatus.FAILED)),
                    File.created_at < now() - timedelta(seconds=settings.stuck_file_after_seconds),
                    File.cleaned_at.is_(None), ~active_upload,
                    or_(File.maintenance_at.is_(None), File.maintenance_at < (
                        now() - timedelta(seconds=settings.worker_retry_seconds)
                    )),
                ).order_by(File.maintenance_at.asc().nullsfirst(), File.id)
                    .limit(settings.worker_batch_size)))

        for file_id in await anyio.to_thread.run_sync(candidates):
            try:
                async with upload_lock(file_id):
                    await reconcile_file(file_id, manager, key)
            except HTTPException as exc:
                logger.warning("File reconciliation deferred file_id=%s status=%s", file_id, exc.status_code)
            except StorageUnavailable:
                logger.warning("File cleanup storage unavailable file_id=%s", file_id)


async def reconcile_file(file_id: UUID, manager: PolicyManager, key: DocumentKey) -> None:
    def claim():
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            file = db.get(File, file_id)
            if file is None or file.status not in (
                FileStatus.STAGING, FileStatus.VERIFYING, FileStatus.FAILED,
            ):
                return None
            file.maintenance_at = now()
            file.maintenance_attempts += 1
            if file.status == FileStatus.STAGING:
                # Direct-upload metadata was not durably linked; never fabricate domain rows.
                file.status = FileStatus.FAILED
                file.failure_reason = "STAGING_ABANDONED_METADATA_UNAVAILABLE"
            elif file.status == FileStatus.VERIFYING and not any(
                db.scalar(select(exists().where(model.file_id == file_id)))
                for model in (ClientDocument, VideoInspection, MeterReading, Outage)
            ):
                file.status = FileStatus.FAILED
                file.failure_reason = "VERIFYING_DOMAIN_LINK_MISSING"
            db.commit()
            return file

    file = await anyio.to_thread.run_sync(claim)
    if file is None:
        return
    async with manager.acquire(file.category):
        if file.status == FileStatus.VERIFYING:
            try:
                reader = FileReader(file, manager, key, None, None)
                async with aclosing(reader.chunks()) as chunks:
                    async for _ in chunks:
                        pass
            except IntegrityError:
                return
            except HTTPException:
                if file.maintenance_attempts < get_settings().worker_max_attempts:
                    raise
                await anyio.to_thread.run_sync(
                    finish_reconciliation, file_id, FileStatus.FAILED, "VERIFY_RETRIES_EXHAUSTED"
                )
            else:
                await anyio.to_thread.run_sync(
                    finish_reconciliation, file_id, FileStatus.READY, None
                )
                return
        # A crashed fallback write may exist on either backend.
        backends = {file.storage_backend}
        policy = manager.config.categories[file.category]
        backends.update(backend for backend in (policy.backend, policy.fallback) if backend is not None)
        for backend in backends:
            try:
                await manager.storages[backend].delete(file.category, file.storage_locator)
            except StorageNotFound:
                pass

        def cleaned():
            with Session(get_catalog_engine()) as db:
                current = db.get(File, file_id)
                current.cleaned_at = now()
                db.commit()
        await anyio.to_thread.run_sync(cleaned)


def finish_reconciliation(file_id: UUID, status: FileStatus, reason: str | None) -> None:
    with Session(get_catalog_engine()) as db:
        file = db.get(File, file_id)
        if file is None or file.status != FileStatus.VERIFYING:
            return
        file.status = status
        file.failure_reason = reason
        if status == FileStatus.READY:
            file.ready_at = now()
        db.commit()
        if status == FileStatus.READY:
            FILE_TIME_TO_AVAILABLE_SECONDS.labels(category=file.category.value).observe(
                (file.ready_at - file.created_at).total_seconds()
            )
