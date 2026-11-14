"""Async boundary, per-storage bulkhead, circuit breaker and operation metrics."""
from __future__ import annotations

import io
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from ftplib import Error as FtpError
from typing import BinaryIO, TypeVar

import anyio
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import SQLAlchemyError

from app.core.metrics import (
    CIRCUIT_STATE,
    STORAGE_BYTES_TOTAL,
    STORAGE_OPERATION_DURATION_SECONDS,
)
from app.models.enums import FileCategory, StorageBackend
from app.storage.base import (
    CircuitOpen,
    Health,
    MultipartPart,
    MultipartStorage,
    Storage,
    StorageNotFound,
    StorageTimeout,
    StorageUnavailable,
    StoredObject,
)

logger = logging.getLogger("app.storage")
T = TypeVar("T")


class CircuitBreaker:
    def __init__(self, storage: StorageBackend, failure_threshold: int, reset_seconds: float):
        self.storage = storage
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.generation = 0
        CIRCUIT_STATE.labels(storage=storage.value).set(0)

    def _set_state(self, state: str) -> None:
        self.state = state
        CIRCUIT_STATE.labels(storage=self.storage.value).set(
            {"closed": 0, "half-open": 1, "open": 2}[state]
        )

    def before_call(self) -> int:
        if self.state == "open" and time.monotonic() - self.opened_at >= self.reset_seconds:
            self._set_state("half-open")
            return self.generation
        if self.state != "closed":
            raise CircuitOpen(f"{self.storage.value} circuit is {self.state}")
        return self.generation

    def success(self, generation: int) -> None:
        if generation == self.generation:
            self.failures = 0
            self._set_state("closed")

    def failure(self, generation: int) -> None:
        if generation != self.generation:
            return
        self.failures += 1
        if self.state == "half-open" or self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()
            self.generation += 1
            self._set_state("open")

    def cancel(self, generation: int) -> None:
        if generation == self.generation and self.state == "half-open":
            self.failure(generation)


class _CancellableReader(io.BufferedIOBase):
    def __init__(self, stream: BinaryIO):
        self.stream = stream

    def read(self, size: int = -1) -> bytes:
        anyio.from_thread.check_cancelled()
        return self.stream.read(size)

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        anyio.from_thread.check_cancelled()
        return self.stream.seek(offset, whence)

    def tell(self) -> int:
        return self.stream.tell()

    def seekable(self) -> bool:
        return self.stream.seekable()

    def readable(self) -> bool:
        return True


def _next_chunk(iterator: Iterator[bytes]) -> bytes | None:
    return next(iterator, None)


class ManagedStorage:
    def __init__(
        self,
        backend: StorageBackend,
        adapter: Storage,
        *,
        concurrency: int = 32,
        timeout: float = 30,
        failure_threshold: int = 3,
        reset_seconds: float = 15,
    ):
        self.backend = backend
        self.adapter = adapter
        self.limiter = anyio.CapacityLimiter(concurrency)
        self._operations = anyio.Semaphore(concurrency)
        self.timeout = timeout
        self.breaker = CircuitBreaker(backend, failure_threshold, reset_seconds)

    async def _run(
        self, function: Callable[..., T], *args, deadline: float | None = None
    ) -> T:
        def invoke() -> T:
            anyio.from_thread.check_cancelled()
            result = function(*args)
            anyio.from_thread.check_cancelled()
            return result

        # Never abandon a thread still using a caller-owned stream. Native I/O
        # timeouts bound cancellation latency; the limiter stays held until exit.
        timeout = self.timeout if deadline is None else max(0, deadline - anyio.current_time())
        with anyio.fail_after(timeout) as scope:
            result = await anyio.to_thread.run_sync(invoke, limiter=self.limiter)
            if scope.cancel_called or anyio.current_time() >= scope.deadline:
                raise TimeoutError
            return result

    @asynccontextmanager
    async def _operation(self, category: FileCategory, operation: str) -> AsyncIterator[float]:
        start = time.monotonic()
        deadline = anyio.current_time() + self.timeout
        outcome = "error"
        generation = None
        acquired = False
        try:
            with anyio.fail_after(self.timeout):
                await self._operations.acquire()
            acquired = True
            generation = self.breaker.before_call()
            # Keep cancellation scopes inside _run, never across streamed yields.
            yield deadline
            if anyio.current_time() >= deadline:
                raise TimeoutError
        except CircuitOpen:
            outcome = "circuit_open"
            raise
        except (TimeoutError, StorageTimeout) as exc:
            outcome = "timeout"
            if generation is not None:
                self.breaker.failure(generation)
            logger.warning(
                "storage operation timed out storage=%s operation=%s",
                self.backend.value, operation,
            )
            raise StorageTimeout(f"{self.backend.value} {operation} timed out") from exc
        except StorageNotFound:
            outcome = "not_found"
            if generation is not None:
                self.breaker.success(generation)
            raise
        except (
            OSError, EOFError, FtpError, BotoCoreError, ClientError,
            SQLAlchemyError, StorageUnavailable,
        ) as exc:
            if generation is not None:
                self.breaker.failure(generation)
            logger.warning(
                "storage operation failed storage=%s operation=%s error=%s",
                self.backend.value, operation, type(exc).__name__,
            )
            raise StorageUnavailable(f"{self.backend.value} {operation} failed") from exc
        except BaseException:
            if generation is not None:
                self.breaker.cancel(generation)
            raise
        else:
            outcome = "success"
            if generation is not None:
                self.breaker.success(generation)
        finally:
            if acquired:
                self._operations.release()
            STORAGE_OPERATION_DURATION_SECONDS.labels(
                category=category.value,
                storage=self.backend.value,
                operation=operation,
                outcome=outcome,
            ).observe(time.monotonic() - start)

    def _bytes(self, category: FileCategory, operation: str, size: int) -> None:
        STORAGE_BYTES_TOTAL.labels(
            category=category.value, storage=self.backend.value, operation=operation
        ).inc(size)

    async def put(
        self, category: FileCategory, key: str, stream: BinaryIO, size: int
    ) -> StoredObject:
        async with self._operation(category, "put") as deadline:
            result = await self._run(
                self.adapter.put, key, _CancellableReader(stream), size, deadline=deadline
            )
            self._bytes(category, "put", result.size)
            return result

    async def get(self, category: FileCategory, key: str) -> AsyncIterator[bytes]:
        async with self._operation(category, "get") as deadline:
            iterator = self.adapter.get(key)
            try:
                while (chunk := await self._run(_next_chunk, iterator, deadline=deadline)) is not None:
                    self._bytes(category, "get", len(chunk))
                    yield chunk
            finally:
                close = getattr(iterator, "close", None)
                if close is not None:
                    with anyio.CancelScope(shield=True):
                        await self._run(close)

    async def delete(self, category: FileCategory, key: str) -> None:
        async with self._operation(category, "delete") as deadline:
            await self._run(self.adapter.delete, key, deadline=deadline)

    async def health(self, category: FileCategory) -> Health:
        try:
            async with self._operation(category, "health") as deadline:
                return await self._run(self.adapter.health, deadline=deadline)
        except StorageUnavailable:
            return "down"

    def _multipart(self) -> MultipartStorage:
        if not isinstance(self.adapter, MultipartStorage):
            raise TypeError("Multipart operations require S3 storage")
        return self.adapter

    async def create_multipart(self, category: FileCategory, key: str) -> str:
        async with self._operation(category, "create_multipart") as deadline:
            return await self._run(self._multipart().create_multipart, key, deadline=deadline)

    async def upload_part(
        self,
        category: FileCategory,
        key: str,
        upload_id: str,
        part_number: int,
        stream: BinaryIO,
        size: int,
    ) -> str:
        async with self._operation(category, "upload_part") as deadline:
            etag = await self._run(
                self._multipart().upload_part,
                key, upload_id, part_number, _CancellableReader(stream), size,
                deadline=deadline,
            )
            self._bytes(category, "upload_part", size)
            return etag

    async def complete_multipart(
        self, category: FileCategory, key: str, upload_id: str, parts: Sequence[MultipartPart]
    ) -> StoredObject:
        async with self._operation(category, "complete_multipart") as deadline:
            return await self._run(
                self._multipart().complete_multipart, key, upload_id, parts, deadline=deadline
            )

    async def abort_multipart(self, category: FileCategory, key: str, upload_id: str) -> None:
        async with self._operation(category, "abort_multipart") as deadline:
            await self._run(self._multipart().abort_multipart, key, upload_id, deadline=deadline)
