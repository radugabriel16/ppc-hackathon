"""Blocking adapter contract. Keys are UUIDs; upload streams must be seekable."""
from __future__ import annotations

import io
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Literal, Protocol, runtime_checkable

CHUNK_SIZE = 64 * 1024
MAX_DB_SIZE = 1024 * 1024
Health = Literal["ok", "degraded", "down"]


class StorageUnavailable(Exception):
    pass


class StorageTimeout(StorageUnavailable):
    pass


class CircuitOpen(StorageUnavailable):
    pass


class StorageNotFound(Exception):
    pass


@dataclass(frozen=True)
class StoredObject:
    locator: str
    size: int


@dataclass(frozen=True)
class InventoryObject:
    key: str
    modified_at: datetime


@dataclass(frozen=True)
class InventoryPage:
    objects: list[InventoryObject]
    next_cursor: uuid.UUID | None


@dataclass(frozen=True)
class MultipartPart:
    part_number: int
    etag: str
    size: int


class Storage(Protocol):
    def put(self, key: str, stream: BinaryIO, size: int) -> StoredObject: ...
    def get(self, key: str) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...
    def health(self) -> Health: ...


@runtime_checkable
class InventoryStorage(Storage, Protocol):
    def inventory(self, cursor: uuid.UUID | None, limit: int) -> InventoryPage: ...


@runtime_checkable
class MultipartStorage(Storage, Protocol):
    def create_multipart(self, key: str) -> str: ...
    def upload_part(
        self, key: str, upload_id: str, part_number: int, stream: BinaryIO, size: int
    ) -> str: ...
    def complete_multipart(
        self, key: str, upload_id: str, parts: Sequence[MultipartPart]
    ) -> StoredObject: ...
    def abort_multipart(self, key: str, upload_id: str) -> None: ...


def object_key(key: str) -> str:
    return str(uuid.UUID(key))


def check_stream(stream: BinaryIO, size: int) -> None:
    if size < 0:
        raise ValueError("size must not be negative")
    if not stream.seekable():
        raise ValueError("Storage uploads require a seekable, bounded stream")
    start = stream.tell()
    end = stream.seek(0, io.SEEK_END)
    stream.seek(start)
    if end - start != size:
        raise ValueError("Declared size does not match the upload stream")
