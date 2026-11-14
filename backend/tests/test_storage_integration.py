import hashlib
import io
import os
import uuid

import pytest
from prometheus_client import REGISTRY

from app.core.metrics import STORAGE_FALLBACK_TOTAL
from app.core.policy_schema import load_policies
from app.core.settings import get_settings
from app.models.enums import FileCategory, StorageBackend
from app.policies.service import PolicyManager
from app.storage.base import CHUNK_SIZE, MultipartPart, StorageNotFound
from app.storage.registry import create_storages
from app.storage.s3 import S3Storage

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def digest(storage, category, key):
    sha256 = hashlib.sha256()
    size = 0
    async for chunk in storage.get(category, key):
        assert len(chunk) <= CHUNK_SIZE
        sha256.update(chunk)
        size += len(chunk)
    return sha256.digest(), size


@pytest.mark.parametrize(
    ("backend", "category"),
    [
        (StorageBackend.db, FileCategory.METER_READING),
        (StorageBackend.ftp, FileCategory.OUTAGE_RECORD),
        (StorageBackend.s3, FileCategory.DRONE_VIDEO),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
async def test_real_storage_roundtrip(policy_manager, backend, category, empty):
    storage = policy_manager.storages[backend]
    key = str(uuid.uuid4())
    payload = b"" if empty else os.urandom(193 * 1024) + b"\x00\r\n\xff"
    assert await storage.health(category) == "ok"
    try:
        stored = await storage.put(category, key, io.BytesIO(payload), len(payload))
        assert (stored.locator, stored.size) == (key, len(payload))
        assert await digest(storage, category, key) == (
            hashlib.sha256(payload).digest(), len(payload)
        )
    finally:
        await storage.delete(category, key)
    await storage.delete(category, key)
    with pytest.raises(StorageNotFound):
        await digest(storage, category, key)
    assert storage.breaker.state == "closed"


async def test_real_policy_primary(policy_manager):
    category = FileCategory.OUTAGE_RECORD
    key = str(uuid.uuid4())
    try:
        result = await policy_manager.put(category, key, io.BytesIO(b"outage"), 6)
        assert result.backend == StorageBackend.ftp
        assert not result.fallback_used
        assert await digest(policy_manager.storages[result.backend], category, key) == (
            hashlib.sha256(b"outage").digest(), 6
        )
    finally:
        await policy_manager.storages[StorageBackend.ftp].delete(category, key)


async def test_real_s3_multipart_complete_and_abort(policy_manager):
    storage = policy_manager.storages[StorageBackend.s3]
    adapter = storage.adapter
    assert isinstance(adapter, S3Storage)
    category = FileCategory.DRONE_VIDEO
    key = str(uuid.uuid4())
    upload_id = await storage.create_multipart(category, key)
    completed = False
    payloads = [os.urandom(5 * 1024 * 1024), os.urandom(71 * 1024)]
    try:
        parts = []
        for number, payload in enumerate(payloads, 1):
            etag = await storage.upload_part(
                category, key, upload_id, number, io.BytesIO(payload), len(payload)
            )
            parts.append(MultipartPart(number, etag, len(payload)))
        stored = await storage.complete_multipart(category, key, upload_id, parts)
        completed = True
        expected = hashlib.sha256()
        for payload in payloads:
            expected.update(payload)
        assert stored.size == sum(map(len, payloads))
        assert await digest(storage, category, key) == (expected.digest(), stored.size)
    finally:
        if not completed:
            await storage.abort_multipart(category, key, upload_id)
        await storage.delete(category, key)

    upload_id = await storage.create_multipart(category, key)
    try:
        await storage.upload_part(category, key, upload_id, 1, io.BytesIO(b"x"), 1)
        uploads = await storage._run(
            lambda: adapter.client.list_multipart_uploads(Bucket=adapter.bucket)
        )
        assert upload_id in {upload["UploadId"] for upload in uploads.get("Uploads", [])}
    finally:
        await storage.abort_multipart(category, key, upload_id)
    uploads = await storage._run(
        lambda: adapter.client.list_multipart_uploads(Bucket=adapter.bucket)
    )
    assert upload_id not in {upload["UploadId"] for upload in uploads.get("Uploads", [])}
    with pytest.raises(StorageNotFound):
        await digest(storage, category, key)


@pytest.mark.ftp_down
async def test_stopped_ftp_opens_circuit_and_falls_back():
    settings = get_settings().model_copy(
        update={
            "storage_circuit_failure_threshold": 2,
            "storage_circuit_reset_seconds": 60,
            "storage_io_timeout_seconds": 1,
        }
    )
    manager = PolicyManager(load_policies(settings.policies_path), create_storages(settings))
    category = FileCategory.OUTAGE_RECORD
    ftp = manager.storages[StorageBackend.ftp]
    s3 = manager.storages[StorageBackend.s3]
    payload = os.urandom(129 * 1024)
    labels = {"category": category.value, "from": "ftp", "to": "s3"}
    fallback_count = STORAGE_FALLBACK_TOTAL.labels(**labels)._value.get()
    for attempt in range(3):
        key = str(uuid.uuid4())
        try:
            result = await manager.put(category, key, io.BytesIO(payload), len(payload))
            assert result.backend == StorageBackend.s3
            assert result.fallback_used
            assert result.stored.locator == key
            assert await digest(s3, category, key) == (
                hashlib.sha256(payload).digest(), len(payload)
            )
        finally:
            await s3.delete(category, key)
        assert ftp.breaker.state == ("closed" if attempt == 0 else "open")
    assert ftp.breaker.failures == 2
    assert REGISTRY.get_sample_value("filegrid_circuit_state", {"storage": "ftp"}) == 2
    assert REGISTRY.get_sample_value(
        "filegrid_storage_operation_duration_seconds_count",
        {"category": category.value, "storage": "ftp", "operation": "put", "outcome": "circuit_open"},
    ) == 1
    assert STORAGE_FALLBACK_TOTAL.labels(**labels)._value.get() == fallback_count + 3
