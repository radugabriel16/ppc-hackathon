"""Passive binary FTP transfers with bounded reads and socket timeouts."""
from collections.abc import Iterator
from contextlib import contextmanager
from ftplib import FTP, error_perm
from datetime import datetime, timezone
from heapq import nsmallest
from time import monotonic
from typing import BinaryIO
from uuid import UUID

from app.storage.base import (
    CHUNK_SIZE,
    Health,
    InventoryObject,
    InventoryPage,
    StorageNotFound,
    StorageTimeout,
    StoredObject,
    check_stream,
    object_key,
)


class FtpStorage:
    def __init__(self, host: str, port: int, user: str, password: str, timeout: float):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout

    @contextmanager
    def _connection(self) -> Iterator[FTP]:
        ftp = FTP(timeout=self.timeout)
        try:
            ftp.connect(self.host, self.port)
            ftp.login(self.user, self.password)
            ftp.set_pasv(True)
            ftp.voidcmd("TYPE I")
            yield ftp
        finally:
            ftp.close()

    def put(self, key: str, stream: BinaryIO, size: int) -> StoredObject:
        key = object_key(key)
        check_stream(stream, size)
        with self._connection() as ftp:
            ftp.storbinary(f"STOR {key}", stream, blocksize=CHUNK_SIZE)
        return StoredObject(key, size)

    def get(self, key: str) -> Iterator[bytes]:
        key = object_key(key)
        with self._connection() as ftp:
            try:
                data = ftp.transfercmd(f"RETR {key}")
            except error_perm as exc:
                if str(exc).startswith("550") and "No such file" in str(exc):
                    raise StorageNotFound("FTP object does not exist") from exc
                raise
            with data:
                data.settimeout(self.timeout)
                while chunk := data.recv(CHUNK_SIZE):
                    yield chunk
            ftp.voidresp()

    def delete(self, key: str) -> None:
        key = object_key(key)
        with self._connection() as ftp:
            try:
                ftp.delete(key)
            except error_perm as exc:
                if not (str(exc).startswith("550") and "No such file" in str(exc)):
                    raise

    def health(self) -> Health:
        with self._connection() as ftp:
            ftp.voidcmd("NOOP")
        return "ok"

    def inventory(self, cursor: UUID | None, limit: int) -> InventoryPage:
        # FTP has no server-side pagination. Stream MLSD with bounded memory/time.
        with self._connection() as ftp:
            deadline = monotonic() + self.timeout
            with ftp.transfercmd("MLSD") as data:
                data.settimeout(self.timeout)
                with data.makefile("r", encoding="utf-8") as lines:
                    def entries():
                        for line in lines:
                            if monotonic() >= deadline:
                                raise StorageTimeout("FTP inventory deadline exceeded")
                            facts, key = line.rstrip("\r\n").split(" ", 1)
                            values = dict(
                                fact.lower().split("=", 1) for fact in facts.split(";") if fact
                            )
                            if values.get("type") != "file":
                                continue
                            key = object_key(key)
                            if cursor is None or UUID(key) > cursor:
                                yield InventoryObject(
                                    key, datetime.strptime(
                                        values["modify"].split(".")[0], "%Y%m%d%H%M%S"
                                    ).replace(tzinfo=timezone.utc),
                                )
                    objects = nsmallest(limit, entries(), key=lambda item: item.key)
            ftp.voidresp()
        return InventoryPage(
            objects, UUID(objects[-1].key) if len(objects) == limit else None,
        )
