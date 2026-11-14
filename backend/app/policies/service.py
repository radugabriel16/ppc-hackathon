"""Validated policy snapshots and resizable category bulkheads."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import BinaryIO

import anyio
from fastapi import HTTPException

from app.core.metrics import REQUESTS_REJECTED_TOTAL, STORAGE_FALLBACK_TOTAL
from app.core.policy_schema import CategoryPolicy, PoliciesConfig
from app.models.enums import FileCategory, StorageBackend
from app.storage.base import StorageUnavailable, StoredObject
from app.storage.resilience import ManagedStorage

logger = logging.getLogger("app.policies")


@dataclass(frozen=True)
class StorageWrite:
    backend: StorageBackend
    stored: StoredObject
    fallback_used: bool = False


class PolicyManager:
    def __init__(
        self, config: PoliciesConfig, storages: dict[StorageBackend, ManagedStorage]
    ):
        self.config = config
        self.storages = storages
        self.reload_lock = anyio.Lock()
        # CapacityLimiter is a resizable semaphore: existing borrowers survive reload.
        self.bulkheads = {
            category: anyio.CapacityLimiter(policy.max_concurrency)
            for category, policy in config.categories.items()
        }

    def activate(self, config: PoliciesConfig) -> None:
        for category, policy in config.categories.items():
            self.bulkheads[category].total_tokens = policy.max_concurrency
        self.config = config

    @asynccontextmanager
    async def acquire(self, category: FileCategory) -> AsyncIterator[CategoryPolicy]:
        limiter = self.bulkheads[category]
        try:
            limiter.acquire_nowait()
        except anyio.WouldBlock as exc:
            REQUESTS_REJECTED_TOTAL.labels(category=category.value, reason="bulkhead").inc()
            raise HTTPException(
                status_code=503,
                detail={"code": "BULKHEAD_FULL", "message": "Category concurrency limit reached"},
                headers={"Retry-After": "1"},
            ) from exc
        try:
            yield self.config.categories[category]
        finally:
            limiter.release()

    async def put(
        self, category: FileCategory, key: str, stream: BinaryIO, size: int,
        *, plaintext_size: int | None = None,
    ) -> StorageWrite:
        async with self.acquire(category) as policy:
            if (size if plaintext_size is None else plaintext_size) > policy.max_size_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "FILE_TOO_LARGE", "message": "File exceeds category size limit"},
                )
            start = stream.tell()
            try:
                stored = await self.storages[policy.backend].put(category, key, stream, size)
                return StorageWrite(policy.backend, stored)
            except StorageUnavailable as exc:
                if not (
                    category == FileCategory.OUTAGE_RECORD
                    and policy.backend == StorageBackend.ftp
                    and policy.fallback == StorageBackend.s3
                ):
                    raise self._unavailable() from exc
                logger.warning("outage storage falling back from ftp to s3")
                stream.seek(start)
                try:
                    stored = await self.storages[StorageBackend.s3].put(category, key, stream, size)
                except StorageUnavailable as fallback_exc:
                    raise self._unavailable() from fallback_exc
                STORAGE_FALLBACK_TOTAL.labels(
                    **{"category": category.value, "from": "ftp", "to": "s3"}
                ).inc()
                return StorageWrite(StorageBackend.s3, stored, fallback_used=True)

    @staticmethod
    def _unavailable() -> HTTPException:
        return HTTPException(
            status_code=503,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "Storage is temporarily unavailable"},
            headers={"Retry-After": "1"},
        )
