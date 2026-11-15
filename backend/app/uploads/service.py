from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from contextlib import aclosing
from datetime import datetime, timedelta, timezone
from tempfile import SpooledTemporaryFile

import anyio
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.files.multipart import SPOOL_SIZE
from app.files.schemas import DroneVideoMetadata
from app.files.service import linked_region
from app.inspections.service import link_inspection
from app.models.enums import FileStatus, StorageBackend
from app.models.files import File
from app.models.uploads import UploadPart, UploadSession
from app.policies.service import PolicyManager
from app.storage.base import MultipartPart, StorageNotFound, StorageUnavailable
from app.uploads.locking import upload_lock
from app.uploads.schemas import UploadComplete, UploadCreate

logger = logging.getLogger("app.uploads")
ACTIVE_STATUSES = ("PENDING", "UPLOADING", "COMPLETING")
SESSION_TTL = timedelta(hours=24)


def now() -> datetime:
    return datetime.now(timezone.utc)


def get_upload(db: Session, upload_id: uuid.UUID, actor_id: uuid.UUID | None) -> UploadSession:
    upload = db.get(UploadSession, upload_id)
    if upload is None:
        raise HTTPException(404, "Upload session not found")
    if upload.created_by != actor_id:
        raise HTTPException(403, "Upload session belongs to another user")
    return upload


def require_active(upload: UploadSession, *statuses: str) -> None:
    if upload.status not in statuses or upload.expires_at <= now():
        raise HTTPException(
            409, {"code": "UPLOAD_NOT_ACTIVE", "message": "Upload session is closed or expired"}
        )


def load_upload(upload_id: uuid.UUID, actor_id: uuid.UUID | None) -> UploadSession:
    with Session(get_catalog_engine(), expire_on_commit=False) as db:
        return get_upload(db, upload_id, actor_id)


async def create_upload(
    data: UploadCreate, actor_id: uuid.UUID, manager: PolicyManager,
) -> dict:
    async with manager.acquire(data.category) as policy:
        if not policy.resumable or policy.backend != StorageBackend.s3 or policy.encryption:
            raise HTTPException(422, "Category does not support resumable S3 uploads")
        if data.size_bytes > policy.max_size_bytes:
            raise HTTPException(413, "File exceeds the category size limit")
        chunk_size = policy.chunk_size_bytes
        if chunk_size is None:
            raise HTTPException(422, "Resumable category requires a chunk size")
        total_parts = (data.size_bytes + chunk_size - 1) // chunk_size
        if total_parts > 10000 or (total_parts > 1 and chunk_size < 5 * 1024 * 1024):
            raise HTTPException(422, "Chunk size is incompatible with S3 multipart limits")
        upload_id, file_id = uuid.uuid4(), uuid.uuid4()
        created_at = now()

        def stage():
            with Session(get_catalog_engine()) as db:
                db.add(File(
                    id=file_id, region_id=linked_region(db, data.metadata),
                    category=data.category, original_name=data.file_name,
                    media_type=data.media_type or mimetypes.guess_type(data.file_name)[0] or "application/octet-stream",
                    size_bytes=data.size_bytes,
                    sha256=data.sha256 or "", storage_backend=StorageBackend.s3,
                    storage_locator=str(file_id), fallback_used=False,
                    status=FileStatus.STAGING, encrypted=False, uploaded_by=actor_id,
                    created_at=created_at,
                    captured_at=data.metadata.captured_at or data.metadata.recorded_at,
                    description=data.metadata.description,
                ))
                db.flush()
                db.add(UploadSession(
                    id=upload_id, category=data.category, file_name=data.file_name,
                    size_bytes=data.size_bytes, chunk_size=chunk_size, total_parts=total_parts,
                    file_id=file_id, status="PENDING",
                    metadata_json=data.metadata.model_dump(mode="json", by_alias=True),
                    created_by=actor_id, created_at=created_at, updated_at=created_at,
                    expires_at=created_at + SESSION_TTL,
                ))
                db.commit()

        storage = manager.storages[StorageBackend.s3]
        async with upload_lock(upload_id):
            await anyio.to_thread.run_sync(stage)
            s3_id = None
            try:
                s3_id = await storage.create_multipart(data.category, str(file_id))

                def activate():
                    with Session(get_catalog_engine()) as db:
                        upload = get_upload(db, upload_id, actor_id)
                        upload.s3_upload_id = s3_id
                        upload.status = "UPLOADING"
                        upload.updated_at = now()
                        db.commit()

                await anyio.to_thread.run_sync(activate)
            except BaseException as exc:
                with anyio.CancelScope(shield=True):
                    try:
                        await terminate_upload(upload_id, actor_id, manager, "ABORTED", s3_id=s3_id)
                    except (SQLAlchemyError, StorageUnavailable):
                        logger.exception("Could not clean up failed multipart creation upload_id=%s", upload_id)
                if isinstance(exc, StorageUnavailable):
                    raise manager._unavailable() from exc
                raise
        return {
            "uploadId": upload_id, "chunkSize": chunk_size, "totalParts": total_parts,
            "expiresAt": created_at + SESSION_TTL,
        }


async def put_part(
    upload_id: uuid.UUID, part_number: int, digest: str, request: Request,
    actor_id: uuid.UUID, manager: PolicyManager,
) -> dict:
    async with upload_lock(upload_id):
        upload = await anyio.to_thread.run_sync(load_upload, upload_id, actor_id)
        require_active(upload, "UPLOADING")
        if not 1 <= part_number <= upload.total_parts:
            raise HTTPException(422, "Part number is outside this upload")
        expected_size = min(
            upload.chunk_size, upload.size_bytes - (part_number - 1) * upload.chunk_size
        )
        async with manager.acquire(upload.category):
            length = request.headers.get("Content-Length")
            if length is not None:
                try:
                    supplied_size = int(length)
                except ValueError as exc:
                    raise HTTPException(422, "Invalid Content-Length") from exc
                if supplied_size > expected_size:
                    raise HTTPException(413, "Part exceeds the expected size")
                if supplied_size != expected_size:
                    raise HTTPException(422, "Part size does not match the session")
            with SpooledTemporaryFile(max_size=SPOOL_SIZE) as stream:
                actual = hashlib.sha256()
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > expected_size:
                        raise HTTPException(413, "Part exceeds the expected size")
                    actual.update(chunk)
                    await anyio.to_thread.run_sync(stream.write, chunk)
                if size != expected_size or actual.hexdigest() != digest:
                    raise HTTPException(422, "Part size or SHA-256 mismatch")
                require_active(upload, "UPLOADING")

                def existing():
                    with Session(get_catalog_engine()) as db:
                        part = db.get(UploadPart, (upload_id, part_number))
                        if part is None:
                            return None
                        if part.sha256 != digest or part.size_bytes != size:
                            raise HTTPException(422, "Part was already received with different bytes")
                        return {"partNumber": part_number, "etag": part.etag}

                duplicate = await anyio.to_thread.run_sync(existing)
                if duplicate is not None:
                    return duplicate
                if upload.s3_upload_id is None or upload.file_id is None:
                    raise HTTPException(409, "Multipart upload is not initialized")
                stream.seek(0)
                try:
                    etag = await manager.storages[StorageBackend.s3].upload_part(
                        upload.category, str(upload.file_id), upload.s3_upload_id,
                        part_number, stream, size,
                    )
                except StorageUnavailable as exc:
                    raise manager._unavailable() from exc

                def persist():
                    with Session(get_catalog_engine()) as db:
                        current = get_upload(db, upload_id, actor_id)
                        db.add(UploadPart(
                            upload_id=upload_id, part_number=part_number, sha256=digest,
                            etag=etag, size_bytes=size, received_at=now(),
                        ))
                        current.updated_at = now()
                        db.commit()

                await anyio.to_thread.run_sync(persist)
                return {"partNumber": part_number, "etag": etag}


async def complete_upload(
    upload_id: uuid.UUID, data: UploadComplete, actor_id: uuid.UUID | None, manager: PolicyManager,
) -> dict:
    async with upload_lock(upload_id):
        def prepare():
            with Session(get_catalog_engine(), expire_on_commit=False) as db:
                upload = get_upload(db, upload_id, actor_id)
                file = db.get(File, upload.file_id) if upload.file_id else None
                if file is None:
                    raise HTTPException(409, "Upload file no longer exists")
                if file.sha256 and file.sha256 != data.sha256:
                    raise HTTPException(422, "Completion SHA-256 differs from the declared hash")
                if upload.status == "COMPLETED":
                    return upload, file, [], True, False
                require_active(upload, "UPLOADING", "COMPLETING")
                parts = db.scalars(select(UploadPart).where(
                    UploadPart.upload_id == upload_id
                ).order_by(UploadPart.part_number)).all()
                if (
                    len(parts) != upload.total_parts
                    or [part.part_number for part in parts] != list(range(1, upload.total_parts + 1))
                    or sum(part.size_bytes for part in parts) != upload.size_bytes
                    or any(not part.etag for part in parts)
                ):
                    raise HTTPException(409, "Upload is missing parts")
                retrying = upload.status == "COMPLETING"
                upload.status = "COMPLETING"
                upload.updated_at = now()
                file.sha256 = data.sha256
                db.commit()
                return upload, file, [
                    MultipartPart(part.part_number, part.etag, part.size_bytes) for part in parts
                ], False, retrying

        upload, file, parts, completed, retrying = await anyio.to_thread.run_sync(prepare)
        response = {"fileId": file.id, "status": FileStatus.VERIFYING}
        if completed:
            return response
        async with manager.acquire(upload.category):
            storage = manager.storages[StorageBackend.s3]
            try:
                object_exists = False
                if retrying:
                    # Completion may have succeeded before a timeout or catalog commit failure.
                    try:
                        async with aclosing(storage.get(upload.category, str(file.id))) as chunks:
                            await anext(chunks, None)
                        object_exists = True
                    except StorageNotFound:
                        pass
                if not object_exists:
                    if upload.s3_upload_id is None:
                        raise HTTPException(409, "Multipart upload is not initialized")
                    await storage.complete_multipart(
                        upload.category, str(file.id), upload.s3_upload_id, parts
                    )
            except StorageUnavailable as exc:
                raise manager._unavailable() from exc

            def finish():
                with Session(get_catalog_engine()) as db:
                    current = get_upload(db, upload_id, actor_id)
                    stored_file = db.get(File, file.id)
                    if stored_file is None:
                        raise HTTPException(409, "Upload file no longer exists")
                    metadata = DroneVideoMetadata.model_validate(current.metadata_json)
                    if linked_region(db, metadata) != stored_file.region_id:
                        raise HTTPException(422, "Linked entity region changed during upload")
                    link_inspection(db, stored_file, metadata)
                    stored_file.status = FileStatus.VERIFYING
                    current.status = "COMPLETED"
                    current.s3_upload_id = None
                    current.updated_at = now()
                    db.commit()

            await anyio.to_thread.run_sync(finish)
        return response


async def terminate_upload(
    upload_id: uuid.UUID, actor_id: uuid.UUID | None, manager: PolicyManager, status: str,
    *, s3_id: str | None = None,
) -> None:
    """Caller holds upload_lock; persist the terminal state before touching S3."""
    def mark():
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            upload = get_upload(db, upload_id, actor_id)
            if upload.status == "COMPLETED":
                raise HTTPException(409, "Completed upload cannot be aborted")
            upload.status = status
            upload.updated_at = now()
            if s3_id is not None:
                upload.s3_upload_id = s3_id
            file = db.get(File, upload.file_id) if upload.file_id else None
            if file is not None:
                file.status = FileStatus.FAILED
                file.failure_reason = f"UPLOAD_{status}"
            db.commit()
            return upload

    upload = await anyio.to_thread.run_sync(mark)
    storage = manager.storages[StorageBackend.s3]
    if upload.file_id is not None:
        if upload.s3_upload_id is not None:
            await storage.abort_multipart(
                upload.category, str(upload.file_id), upload.s3_upload_id
            )
        await storage.delete(upload.category, str(upload.file_id))

    def finish():
        with Session(get_catalog_engine()) as db:
            current = get_upload(db, upload_id, actor_id)
            current.s3_upload_id = None
            if current.file_id is not None:
                file = db.get(File, current.file_id)
                if file is not None:
                    file.cleaned_at = now()
            db.commit()

    await anyio.to_thread.run_sync(finish)


async def abort_upload(
    upload_id: uuid.UUID, actor_id: uuid.UUID, manager: PolicyManager,
) -> None:
    async with upload_lock(upload_id):
        upload = await anyio.to_thread.run_sync(load_upload, upload_id, actor_id)
        async with manager.acquire(upload.category):
            try:
                await terminate_upload(
                    upload_id, actor_id, manager,
                    "EXPIRED" if upload.expires_at <= now() else "ABORTED",
                )
            except StorageUnavailable as exc:
                raise manager._unavailable() from exc
