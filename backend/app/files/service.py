from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime, timezone
from tempfile import SpooledTemporaryFile

import anyio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.metrics import FILE_TIME_TO_AVAILABLE_SECONDS, INTEGRITY_FAILURES_TOTAL
from app.documents.encryption import DocumentKey, IntegrityError, decrypt, encrypt
from app.documents.service import document_region, link_document
from app.files.multipart import SPOOL_SIZE, MultipartUpload, direct_limit
from app.files.schemas import (
    ConnectionDocumentMetadata,
    DroneVideoMetadata,
    FileUploadMetadata,
    FileResource,
    OutageRecordMetadata,
)
from app.inspections.service import link_inspection
from app.models.audit import AuditEvent
from app.models.enums import FileCategory, FileStatus
from app.models.files import File
from app.models.geography import NetworkAsset
from app.outages.service import link_outage
from app.policies.service import PolicyManager, StorageWrite
from app.storage.base import StorageNotFound, StorageUnavailable

logger = logging.getLogger("app.files")
SMALL_DOWNLOAD = 10 * 1024 * 1024


def linked_region(db: Session, metadata: FileUploadMetadata) -> uuid.UUID:
    if isinstance(metadata, ConnectionDocumentMetadata):
        region_id = document_region(db, metadata)
    else:
        region_id = db.scalar(
            select(NetworkAsset.region_id)
            .where(NetworkAsset.id == metadata.asset_id)
            .with_for_update()
        )
        if region_id is None:
            raise HTTPException(404, "Network asset not found")
    if metadata.region_id is not None and metadata.region_id != region_id:
        raise HTTPException(
            422, {"code": "REGION_MISMATCH", "message": "File and linked entity regions differ"}
        )
    return region_id


def get_file(db: Session, file_id: uuid.UUID) -> File:
    file = db.get(File, file_id)
    if file is None:
        raise HTTPException(404, "File not found")
    return file


async def store_file(
    upload: MultipartUpload, manager: PolicyManager, key: DocumentKey,
    db: Session, actor_id: uuid.UUID,
) -> FileResource:
    metadata = upload.metadata
    if metadata is None:
        raise ValueError("Parsed metadata is required")
    category = metadata.category
    policy = manager.config.categories[category]
    if upload.size > direct_limit(manager.config, category):
        raise HTTPException(413, "File exceeds the category size limit")
    encrypted = category == FileCategory.CONNECTION_DOCUMENT or policy.encryption is not None
    started = time.monotonic()

    def stage() -> File:
        file_id = uuid.uuid4()
        file = File(
            id=file_id,
            region_id=linked_region(db, metadata),
            category=category,
            original_name=upload.filename,
            media_type=upload.media_type,
            size_bytes=upload.size,
            sha256=upload.sha256.hexdigest(),
            storage_backend=policy.backend,
            storage_locator=str(file_id),
            fallback_used=False,
            status=FileStatus.STAGING,
            encrypted=encrypted,
            encryption_key_id=key.id if encrypted else None,
            uploaded_by=actor_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(file)
        db.commit()
        return file

    file = await anyio.to_thread.run_sync(stage)
    file_id = file.id
    written: StorageWrite | None = None
    try:
        with SpooledTemporaryFile(max_size=SPOOL_SIZE) as ciphertext:
            stream, size = upload.stream, upload.size
            if encrypted:
                size = await anyio.to_thread.run_sync(encrypt, stream, ciphertext, key, file.id)
                ciphertext.seek(0)
                stream = ciphertext
            written = await manager.put(
                category, str(file.id), stream, size, plaintext_size=upload.size
            )

        def finish() -> FileResource:
            if linked_region(db, metadata) != file.region_id:
                raise HTTPException(422, "Linked entity region changed during upload")
            file.storage_backend = written.backend
            file.storage_locator = written.stored.locator
            file.fallback_used = written.fallback_used
            file.status = FileStatus.READY
            file.ready_at = datetime.now(timezone.utc)
            if isinstance(metadata, ConnectionDocumentMetadata):
                link_document(db, file, metadata)
            elif isinstance(metadata, OutageRecordMetadata):
                link_outage(db, file, metadata)
            elif isinstance(metadata, DroneVideoMetadata):
                link_inspection(db, file, metadata)
            result = FileResource.model_validate(file)
            db.commit()
            return result

        result = await anyio.to_thread.run_sync(finish)
    except BaseException:
        # Compensation also runs on client disconnect; never mask the original failure.
        with anyio.CancelScope(shield=True):
            def fail():
                db.rollback()
                failed = db.get(File, file_id)
                if failed is not None:
                    failed.status = FileStatus.FAILED
                    if written is not None:
                        failed.storage_backend = written.backend
                        failed.storage_locator = written.stored.locator
                        failed.fallback_used = written.fallback_used
                    db.commit()

            try:
                await anyio.to_thread.run_sync(fail)
            except SQLAlchemyError:
                logger.exception("Could not mark failed upload")
            backends = (
                {written.backend} if written is not None
                else {policy.backend, policy.fallback} - {None}
            )
            for backend in backends:
                try:
                    await manager.storages[backend].delete(category, str(file_id))
                except (StorageUnavailable, StorageNotFound):
                    logger.warning("Upload cleanup failed storage=%s", backend.value)
        raise
    FILE_TIME_TO_AVAILABLE_SECONDS.labels(category=category.value).observe(time.monotonic() - started)
    return result


def record_check(
    file: File, valid: bool, checked_at: datetime, actor_id: uuid.UUID, request_id: str | None,
) -> None:
    with Session(get_catalog_engine()) as db:
        current = get_file(db, file.id)
        current.last_verified_at = checked_at
        if not valid:
            current.status = FileStatus.CORRUPT
            db.add(
                AuditEvent(
                    actor_id=actor_id, action="FILE_INTEGRITY_FAILED", entity_type="file",
                    entity_id=file.id, occurred_at=checked_at, request_id=request_id,
                    details={"category": file.category.value, "storage": file.storage_backend.value},
                )
            )
        db.commit()
    if not valid:
        INTEGRITY_FAILURES_TOTAL.labels(
            category=file.category.value, storage=file.storage_backend.value
        ).inc()


class FileReader:
    def __init__(
        self, file: File, manager: PolicyManager, key: DocumentKey,
        actor_id: uuid.UUID, request_id: str | None,
    ):
        if file.encrypted and file.encryption_key_id != key.id:
            raise HTTPException(
                503, {"code": "KEY_UNAVAILABLE", "message": "File encryption key is unavailable"},
                headers={"Retry-After": "1"},
            )
        self.file = file
        self.manager = manager
        self.key = key
        self.actor_id = actor_id
        self.request_id = request_id
        self.actual_sha256 = ""
        self.checked_at: datetime | None = None

    async def chunks(self) -> AsyncIterator[bytes]:
        digest = hashlib.sha256()
        size = 0
        storage = self.manager.storages[self.file.storage_backend]
        try:
            async with aclosing(storage.get(self.file.category, self.file.storage_locator)) as raw:
                plaintext = decrypt(raw, self.key, self.file.id) if self.file.encrypted else raw
                async with aclosing(plaintext):
                    async for chunk in plaintext:
                        size += len(chunk)
                        if size > self.file.size_bytes:
                            raise IntegrityError("Stored file exceeds catalog size")
                        digest.update(chunk)
                        yield chunk
            self.actual_sha256 = digest.hexdigest()
            if size != self.file.size_bytes or self.actual_sha256 != self.file.sha256:
                raise IntegrityError("Stored file SHA-256 or size mismatch")
        except (IntegrityError, StorageNotFound) as exc:
            self.checked_at = datetime.now(timezone.utc)
            await anyio.to_thread.run_sync(
                record_check, self.file, False, self.checked_at, self.actor_id, self.request_id
            )
            raise IntegrityError("Stored file failed integrity verification") from exc
        except StorageUnavailable as exc:
            raise self.manager._unavailable() from exc
        else:
            self.checked_at = datetime.now(timezone.utc)
            await anyio.to_thread.run_sync(
                record_check, self.file, True, self.checked_at, self.actor_id, self.request_id
            )

    async def download(self) -> AsyncIterator[bytes]:
        pending = None
        async with aclosing(self.chunks()) as chunks:
            async for chunk in chunks:
                if pending is not None:
                    yield pending
                pending = chunk
        # Hold the last chunk until validation so a bad stream cannot satisfy Content-Length.
        if pending is not None:
            yield pending
