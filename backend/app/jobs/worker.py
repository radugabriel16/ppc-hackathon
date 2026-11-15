import asyncio
import logging
from contextlib import aclosing
from datetime import timedelta
from uuid import UUID

import anyio
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from opentelemetry import trace

from app.core.db import get_catalog_engine
from app.core.metrics import (
    FILE_TIME_TO_AVAILABLE_SECONDS,
    UPLOAD_SESSIONS_ACTIVE,
    UPLOAD_SESSIONS_STALLED,
)
from app.documents.encryption import DocumentKey, IntegrityError
from app.files.service import FileReader
from app.jobs.orphans import delete_orphan_contents
from app.jobs.maintenance import integrity_scrub, reconcile_files
from app.jobs.meter_gaps import detect_meter_gaps
from app.jobs.reminders import send_reminders
from app.jobs.missing_documents import missing_document_issues
from app.jobs.forecasts import daily_forecasts
from app.jobs.scheduling import job_run
from app.models.enums import FileStatus
from app.models.files import File
from app.models.uploads import UploadSession
from app.policies.service import PolicyManager
from app.uploads.locking import upload_lock
from app.uploads.schemas import UploadComplete
from app.uploads.service import (
    ACTIVE_STATUSES,
    complete_upload,
    now,
    terminate_upload,
)

logger = logging.getLogger("app.jobs.worker")
tracer = trace.get_tracer(__name__)

POLL_INTERVAL_SECONDS = 5
STALLED_AFTER = timedelta(minutes=10)
BATCH_SIZE = 100


def pending_jobs():
    with Session(get_catalog_engine()) as db:
        expired = db.scalars(select(UploadSession.id).where(or_(
            (UploadSession.status.in_(ACTIVE_STATUSES)) & (UploadSession.expires_at <= now()),
            (UploadSession.status.in_(("ABORTED", "EXPIRED")))
            & (UploadSession.s3_upload_id.is_not(None)),
        )).order_by(UploadSession.expires_at).limit(BATCH_SIZE)).all()
        completing = db.execute(select(
            UploadSession.id, UploadSession.created_by, File.sha256
        ).join(File, File.id == UploadSession.file_id).where(
            UploadSession.status == "COMPLETING", UploadSession.expires_at > now(),
        ).order_by(UploadSession.updated_at).limit(BATCH_SIZE)).all()
        verifying = db.scalars(select(UploadSession.id).join(
            File, File.id == UploadSession.file_id
        ).where(
            UploadSession.status == "COMPLETED", File.status == FileStatus.VERIFYING,
        ).order_by(UploadSession.updated_at).limit(BATCH_SIZE)).all()
        return expired, completing, verifying


async def expire_upload(upload_id: UUID, manager: PolicyManager) -> None:
    async with upload_lock(upload_id):
        def load():
            with Session(get_catalog_engine(), expire_on_commit=False) as db:
                return db.get(UploadSession, upload_id)

        upload = await anyio.to_thread.run_sync(load)
        if upload is None or upload.status == "COMPLETED":
            return
        if upload.status in ACTIVE_STATUSES and upload.expires_at > now():
            return
        async with manager.acquire(upload.category):
            await terminate_upload(
                upload.id, upload.created_by, manager,
                "EXPIRED" if upload.expires_at <= now() else upload.status,
            )


async def verify_upload(upload_id: UUID, manager: PolicyManager, key: DocumentKey) -> None:
    async with upload_lock(upload_id):
        def load():
            with Session(get_catalog_engine(), expire_on_commit=False) as db:
                upload = db.get(UploadSession, upload_id)
                if upload is None or upload.status != "COMPLETED" or upload.file_id is None:
                    return None
                file = db.get(File, upload.file_id)
                return file if file is not None and file.status == FileStatus.VERIFYING else None

        file = await anyio.to_thread.run_sync(load)
        if file is None:
            return
        async with upload_lock(file.id):
            file = await anyio.to_thread.run_sync(load)
            if file is not None:
                await verify_upload_file(file, manager, key)


async def verify_upload_file(file: File, manager: PolicyManager, key: DocumentKey) -> None:
    async with manager.acquire(file.category):
        reader = FileReader(file, manager, key, file.uploaded_by, None)
        try:
            async with aclosing(reader.chunks()) as chunks:
                async for _ in chunks:
                    pass
        except IntegrityError:
            logger.warning("Multipart upload failed integrity verification file_id=%s", file.id)
            return

        def ready():
            with Session(get_catalog_engine()) as db:
                current = db.get(File, file.id)
                if current is None or current.status != FileStatus.VERIFYING:
                    return False
                current.status = FileStatus.READY
                current.ready_at = now()
                db.commit()
                return True

        if await anyio.to_thread.run_sync(ready):
            FILE_TIME_TO_AVAILABLE_SECONDS.labels(category=file.category.value).observe(
                (now() - file.created_at).total_seconds()
            )


def update_upload_metrics() -> None:
    with Session(get_catalog_engine()) as db:
        active, stalled = db.execute(select(
            func.count(),
            func.count().filter(UploadSession.updated_at < now() - STALLED_AFTER),
        ).where(
            UploadSession.status.in_(ACTIVE_STATUSES), UploadSession.expires_at > now(),
        )).one()
    UPLOAD_SESSIONS_ACTIVE.set(active)
    UPLOAD_SESSIONS_STALLED.set(stalled)


async def run_uploads(manager: PolicyManager, key: DocumentKey) -> None:
    async with job_run("uploads") as run:
        if run:
            await run_upload_jobs(manager, key)


def worker_jobs(manager: PolicyManager, key: DocumentKey):
    return (
        ("uploads", run_uploads, (manager, key)),
        ("integrity_scrub", integrity_scrub, (manager, key)),
        ("reconcile_files", reconcile_files, (manager, key)),
        ("meter_gaps", detect_meter_gaps, ()),
        ("reminders", send_reminders, ()),
        ("missing_document_issues", missing_document_issues, ()),
        ("daily_forecasts", daily_forecasts, ()),
    )


async def run_job(name, job, args) -> None:
    try:
        with tracer.start_as_current_span(f"worker.{name}"):
            await job(*args)
    except Exception:
        logger.exception("Worker job failed job=%s", name)


async def run_worker_once(manager: PolicyManager, key: DocumentKey) -> None:
    for name, job, args in worker_jobs(manager, key):
        await run_job(name, job, args)


async def run_upload_jobs(manager: PolicyManager, key: DocumentKey) -> None:
    expired, completing, verifying = await anyio.to_thread.run_sync(pending_jobs)
    jobs = (
        [(upload_id, expire_upload, (upload_id, manager)) for upload_id in expired]
        + [(row.id, complete_upload, (
            row.id, UploadComplete(sha256=row.sha256), row.created_by, manager,
        )) for row in completing]
        + [(upload_id, verify_upload, (upload_id, manager, key)) for upload_id in verifying]
    )
    for upload_id, job, args in jobs:
        try:
            await job(*args)
        except HTTPException as exc:
            if exc.status_code != 503 or not isinstance(exc.detail, dict) or exc.detail.get("code") != "UPLOAD_BUSY":
                logger.warning("Upload job deferred upload_id=%s status=%s", upload_id, exc.status_code)
        except Exception:
            logger.exception("Upload job failed upload_id=%s", upload_id)
    try:
        with tracer.start_as_current_span("worker.orphan_contents"):
            deleted = await delete_orphan_contents(manager)
        if deleted:
            logger.info("Deleted orphan storage contents count=%s", deleted)
    except Exception:
        logger.exception("Orphan storage cleanup failed")
    await anyio.to_thread.run_sync(update_upload_metrics)


async def run_worker_loop(manager: PolicyManager, key: DocumentKey) -> None:
    logger.info("worker loop started")
    running: dict[str, asyncio.Task] = {}
    try:
        while True:
            for name, job, args in worker_jobs(manager, key):
                if name not in running or running[name].done():
                    running[name] = asyncio.create_task(run_job(name, job, args))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("worker loop stopped")
        raise
    finally:
        for task in running.values():
            task.cancel()
        await asyncio.gather(*running.values(), return_exceptions=True)
