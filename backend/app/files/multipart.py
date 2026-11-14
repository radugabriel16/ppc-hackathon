"""Bounded multipart ingestion without FastAPI's pre-buffered UploadFile dependency."""
from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from tempfile import SpooledTemporaryFile

import anyio
from fastapi import HTTPException, Request
from pydantic import ValidationError
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header

from app.core.policy_schema import PoliciesConfig
from app.files.schemas import FileUploadMetadata, metadata_adapter
from app.models.enums import FileCategory
from app.storage.base import CHUNK_SIZE

SPOOL_SIZE = 1024 * 1024
MAX_METADATA = 16 * 1024
MAX_HEADERS = 8 * 1024


def direct_limit(config: PoliciesConfig, category: FileCategory) -> int:
    policy = config.categories[category]
    if category == FileCategory.DRONE_VIDEO:
        return min(policy.max_size_bytes, policy.chunk_size_bytes or 16 * 1024 * 1024)
    return policy.max_size_bytes


class MultipartUpload:
    def __init__(self, config: PoliciesConfig):
        self.config = config
        self.limit = max(
            direct_limit(config, category)
            for category in FileCategory if category != FileCategory.METER_READING
        )
        self.stream = SpooledTemporaryFile(max_size=SPOOL_SIZE)
        self.sha256 = hashlib.sha256()
        self.size = 0
        self.metadata: FileUploadMetadata | None = None
        self.filename = ""
        self.media_type = "application/octet-stream"
        self.seen: set[bytes] = set()
        self.name = b""
        self.headers: dict[bytes, bytes] = {}
        self.header_name = bytearray()
        self.header_value = bytearray()
        self.header_size = 0
        self.metadata_bytes = bytearray()
        self.ended = False

    def part_begin(self):
        self.headers = {}
        self.header_size = 0

    def _header(self, target: bytearray, data: bytes, start: int, end: int):
        self.header_size += end - start
        if self.header_size > MAX_HEADERS:
            raise HTTPException(422, "Multipart headers are too large")
        target.extend(data[start:end])

    def header_field(self, data: bytes, start: int, end: int):
        self._header(self.header_name, data, start, end)

    def header_value_data(self, data: bytes, start: int, end: int):
        self._header(self.header_value, data, start, end)

    def header_end(self):
        name = bytes(self.header_name).lower()
        if name in self.headers:
            raise HTTPException(422, "Duplicate multipart header")
        self.headers[name] = bytes(self.header_value)
        self.header_name.clear()
        self.header_value.clear()

    def headers_finished(self):
        disposition, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        self.name = options.get(b"name", b"")
        if disposition != b"form-data" or self.name not in (b"file", b"metadata"):
            raise HTTPException(422, "Expected file and metadata multipart fields")
        if self.name in self.seen:
            raise HTTPException(422, "Duplicate multipart field")
        self.seen.add(self.name)
        if self.name == b"file":
            try:
                self.filename = options.get(b"filename", b"").decode("utf-8")
                self.media_type = self.headers.get(
                    b"content-type", b"application/octet-stream"
                ).decode("ascii")
            except UnicodeError as exc:
                raise HTTPException(422, "Invalid file headers") from exc
            if not 1 <= len(self.filename) <= 512 or any(ord(c) < 32 for c in self.filename):
                raise HTTPException(422, "Invalid filename")
            if not 1 <= len(self.media_type) <= 128 or any(
                ord(c) < 32 for c in self.media_type
            ):
                raise HTTPException(422, "Invalid media type")

    def part_data(self, data: bytes, start: int, end: int):
        chunk = data[start:end]
        if self.name == b"metadata":
            if len(self.metadata_bytes) + len(chunk) > MAX_METADATA:
                raise HTTPException(422, "Metadata is too large")
            self.metadata_bytes.extend(chunk)
        else:
            self.size += len(chunk)
            if self.size > self.limit:
                raise HTTPException(413, "File exceeds the direct-upload size limit")
            self.sha256.update(chunk)
            self.stream.write(chunk)

    def part_end(self):
        if self.name == b"metadata":
            try:
                self.metadata = metadata_adapter.validate_json(bytes(self.metadata_bytes))
            except ValidationError as exc:
                raise HTTPException(
                    422, {"code": "INVALID_METADATA", "message": "Invalid file metadata"}
                ) from exc
            self.limit = direct_limit(self.config, self.metadata.category)
            if self.size > self.limit:
                raise HTTPException(413, "File exceeds the category size limit")

    def end(self):
        self.ended = True


@asynccontextmanager
async def parse_upload(request: Request, config: PoliciesConfig) -> AsyncIterator[MultipartUpload]:
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise HTTPException(422, "A multipart/form-data body with a boundary is required")
    upload = MultipartUpload(config)
    callbacks = {
        "on_part_begin": upload.part_begin,
        "on_header_field": upload.header_field,
        "on_header_value": upload.header_value_data,
        "on_header_end": upload.header_end,
        "on_headers_finished": upload.headers_finished,
        "on_part_data": upload.part_data,
        "on_part_end": upload.part_end,
        "on_end": upload.end,
    }
    try:
        parser = MultipartParser(boundary, callbacks)
        received = 0
        body_limit = upload.limit + 2 * MAX_HEADERS + MAX_METADATA + 4096
        async for chunk in request.stream():
            received += len(chunk)
            if received > body_limit:
                raise HTTPException(413, "Multipart request is too large")
            for offset in range(0, len(chunk), CHUNK_SIZE):
                await anyio.to_thread.run_sync(parser.write, chunk[offset:offset + CHUNK_SIZE])
        parser.finalize()
        if not upload.ended or upload.seen != {b"file", b"metadata"} or upload.metadata is None:
            raise HTTPException(422, "Incomplete multipart request")
        upload.stream.seek(0)
        yield upload
    except MultipartParseError as exc:
        raise HTTPException(422, "Malformed multipart request") from exc
    finally:
        await anyio.to_thread.run_sync(upload.stream.close)
