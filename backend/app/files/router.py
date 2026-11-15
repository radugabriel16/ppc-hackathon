from contextlib import aclosing
import re
from datetime import datetime, timezone
from tempfile import SpooledTemporaryFile
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.auth.dependencies import get_current_user
from app.core.api import Pagination, paginate
from app.core.db import get_catalog_db
from app.core.logging import get_request_id
from app.core.metrics import DOCUMENT_ACCESS_TOTAL
from app.documents.encryption import IntegrityError
from app.files.multipart import SPOOL_SIZE, parse_upload
from app.files.schemas import FileResource
from app.files.service import SMALL_DOWNLOAD, FileReader, get_file, store_file
from app.geography.service import region_filter
from app.models.audit import AuditEvent
from app.models.auth import AppUser
from app.models.enums import FileCategory, FileStatus
from app.models.files import File
from app.storage.base import CHUNK_SIZE
from app.storage.base import RangeStorage

router = APIRouter(prefix="/api/v1", tags=["files"])


def request_id() -> str | None:
    return (get_request_id() or "")[:64] or None


@router.post("/files", status_code=201, response_model=FileResource)
async def upload_file(
    request: Request,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    actor_id = user.id
    await anyio.to_thread.run_sync(db.commit)
    manager = request.app.state.policy_manager
    async with parse_upload(request, manager.config) as upload:
        return await store_file(upload, manager, request.app.state.document_key, db, actor_id)


@router.get("/files", dependencies=[Depends(get_current_user)])
def list_files(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    category: FileCategory | None = None,
    status: FileStatus | None = None,
    include_meter_readings: Annotated[bool, Query(alias="includeMeterReadings")] = False,
    pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    statement = select(File).where(File.region_id.is_not(None))
    if category is None and not include_meter_readings:
        statement = statement.where(File.category != FileCategory.METER_READING)
    if region_id is not None:
        statement = statement.where(region_filter(File, region_id))
    for column, value in ((File.subregion_id, subregion_id), (File.category, category), (File.status, status)):
        if value is not None:
            statement = statement.where(column == value)
    return paginate(db, statement.order_by(File.created_at.desc(), File.id), pagination, FileResource)


@router.get("/files/{id}", response_model=FileResource, dependencies=[Depends(get_current_user)])
def file_metadata(id: UUID, db: Session = Depends(get_catalog_db)):
    return get_file(db, id)


def prepare_reader(
    request: Request, db: Session, id: UUID, actor_id: UUID, *, download: bool = False, view: bool = False,
) -> FileReader:
    file = get_file(db, id)
    allowed = {FileStatus.READY} if download else {FileStatus.READY, FileStatus.CORRUPT}
    if file.status not in allowed:
        raise HTTPException(
            409, {"code": "FILE_NOT_READY", "message": f"File is {file.status.value}"}
        )
    reader = FileReader(
        file, request.app.state.policy_manager, request.app.state.document_key, actor_id, request_id()
    )
    if download and file.category == FileCategory.CONNECTION_DOCUMENT:
        db.add(
            AuditEvent(
                actor_id=actor_id, action="DOCUMENT_VIEW_REQUESTED" if view else "DOCUMENT_DOWNLOAD_REQUESTED", entity_type="file",
                entity_id=file.id, occurred_at=datetime.now(timezone.utc), request_id=request_id(),
            )
        )
    db.commit()
    if download and file.category == FileCategory.CONNECTION_DOCUMENT:
        reader.document_action = "view" if view else "download"
        DOCUMENT_ACCESS_TOTAL.labels(action=reader.document_action, outcome="requested").inc()
    return reader


@router.get("/files/{id}/verify")
async def verify_file(
    id: UUID, request: Request, user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    reader = await anyio.to_thread.run_sync(prepare_reader, request, db, id, user.id)
    valid = True
    try:
        async with aclosing(reader.chunks()) as chunks:
            async for _ in chunks:
                pass
    except IntegrityError:
        valid = False
    return {
        "valid": valid, "expectedSha256": reader.file.sha256,
        "actualSha256": reader.actual_sha256, "checkedAt": reader.checked_at,
    }


@router.get("/files/{id}/download")
async def download_file(
    id: UUID, request: Request, inline: bool = False, user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    def prepare():
        return prepare_reader(request, db, id, user.id, download=True, view=inline)

    reader = await anyio.to_thread.run_sync(prepare)
    supports_range = (
        not reader.file.encrypted
        and isinstance(
            reader.manager.storages[reader.file.storage_backend].adapter, RangeStorage,
        )
    )
    headers = {
        "Content-Length": str(reader.file.size_bytes),
        "Content-Disposition": f"{'inline' if inline and (reader.file.media_type in {'application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp'} or reader.file.media_type.startswith('video/')) else 'attachment'}; filename*=UTF-8''{quote(reader.file.original_name, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Content-Security-Policy": "sandbox",
        "Accept-Ranges": "bytes" if supports_range else "none",
    }
    byte_range = request.headers.get("Range")
    if byte_range and supports_range:
        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", byte_range)
        size = reader.file.size_bytes
        if match is None or not any(match.groups()) or size == 0:
            raise HTTPException(416, "Invalid byte range", headers={"Content-Range": f"bytes */{size}"})
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            start, end = max(0, size - int(last)), size - 1
        if start > end or start >= size:
            raise HTTPException(416, "Unsatisfiable byte range", headers={"Content-Range": f"bytes */{size}"})
        if reader.file.last_verified_at is None:
            raise HTTPException(
                409, {"code": "INTEGRITY_NOT_VERIFIED", "message": "Verify file integrity before partial playback"},
            )
        headers["Content-Length"] = str(end - start + 1)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(
            reader.range_chunks(start, end), status_code=206,
            media_type=reader.file.media_type, headers=headers,
        )
    if reader.file.size_bytes > SMALL_DOWNLOAD:
        return StreamingResponse(reader.download(), media_type=reader.file.media_type, headers=headers)
    buffer = SpooledTemporaryFile(max_size=SPOOL_SIZE)
    try:
        async with aclosing(reader.chunks()) as chunks:
            async for chunk in chunks:
                await anyio.to_thread.run_sync(buffer.write, chunk)
        buffer.seek(0)
    except BaseException as exc:
        buffer.close()
        if isinstance(exc, IntegrityError):
            raise HTTPException(
                409, {"code": "FILE_CORRUPT", "message": "File failed integrity verification"}
            ) from exc
        raise

    async def buffered():
        try:
            while chunk := await anyio.to_thread.run_sync(buffer.read, CHUNK_SIZE):
                yield chunk
        finally:
            buffer.close()

    return StreamingResponse(
        buffered(), media_type=reader.file.media_type, headers=headers,
        background=BackgroundTask(buffer.close),
    )
