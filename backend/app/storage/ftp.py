"""Passive binary FTP transfers with bounded reads and socket timeouts."""
from collections.abc import Iterator
from contextlib import contextmanager
from ftplib import FTP, error_perm
from typing import BinaryIO

from app.storage.base import (
    CHUNK_SIZE,
    Health,
    StorageNotFound,
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
