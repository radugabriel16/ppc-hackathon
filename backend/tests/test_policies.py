import io
import uuid
from pathlib import Path

import anyio
import pytest
from fastapi import HTTPException

from app.core.policy_schema import PoliciesConfig, load_policies
from app.models.enums import FileCategory, StorageBackend
from app.policies.service import PolicyManager
from app.storage.resilience import ManagedStorage
from tests.test_storage_resilience import Adapter

pytestmark = pytest.mark.anyio
CATEGORY = FileCategory.OUTAGE_RECORD


@pytest.fixture
def manager():
    config = load_policies(Path(__file__).resolve().parents[2] / "config/policies.yaml")
    return PolicyManager(
        config,
        {backend: ManagedStorage(backend, Adapter()) for backend in StorageBackend},
    )


async def test_bulkhead_reload_preserves_inflight_borrowers(manager):
    raw = manager.config.model_dump(by_alias=True)
    raw["categories"][CATEGORY]["maxConcurrency"] = 2
    manager.activate(PoliciesConfig.model_validate(raw))
    both_started = anyio.Event()
    release = anyio.Event()
    active = []

    async def hold():
        async with manager.acquire(CATEGORY):
            active.append(True)
            if len(active) == 2:
                both_started.set()
            await release.wait()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(hold)
        tasks.start_soon(hold)
        await both_started.wait()
        raw["categories"][CATEGORY]["maxConcurrency"] = 1
        manager.activate(PoliciesConfig.model_validate(raw))
        with pytest.raises(HTTPException) as error:
            async with manager.acquire(CATEGORY):
                pytest.fail("Reload must not reset existing concurrency usage")
        assert error.value.status_code == 503
        assert error.value.headers["Retry-After"] == "1"
        release.set()
    async with manager.acquire(CATEGORY):
        pass
    assert manager.bulkheads[CATEGORY].borrowed_tokens == 0


async def test_failed_primary_rewinds_stream_before_fallback(manager):
    manager.storages[StorageBackend.ftp].adapter.fail = True
    stream = io.BytesIO(b"prefix:original bytes")
    stream.seek(7)
    result = await manager.put(CATEGORY, str(uuid.uuid4()), stream, 14)
    assert result.backend == StorageBackend.s3
    assert result.fallback_used
    assert manager.storages[StorageBackend.s3].adapter.content == b"original bytes"


async def test_unavailable_primary_without_allowed_fallback_returns_503(manager):
    category = FileCategory.METER_READING
    manager.storages[StorageBackend.db].adapter.fail = True
    with pytest.raises(HTTPException) as error:
        await manager.put(category, str(uuid.uuid4()), io.BytesIO(b"x"), 1)
    assert error.value.status_code == 503
    assert error.value.headers["Retry-After"] == "1"
    assert manager.storages[StorageBackend.s3].adapter.content == b""
    assert manager.bulkheads[category].borrowed_tokens == 0


async def test_unavailable_fallback_returns_503(manager):
    for backend in (StorageBackend.ftp, StorageBackend.s3):
        manager.storages[backend].adapter.fail = True
    with pytest.raises(HTTPException) as error:
        await manager.put(CATEGORY, str(uuid.uuid4()), io.BytesIO(b"x"), 1)
    assert error.value.status_code == 503
    assert manager.bulkheads[CATEGORY].borrowed_tokens == 0


async def test_size_limit_rejects_before_storage_and_releases_bulkhead(manager):
    with pytest.raises(HTTPException) as error:
        await manager.put(
            CATEGORY, str(uuid.uuid4()), io.BytesIO(b"x"),
            manager.config.categories[CATEGORY].max_size_bytes + 1,
        )
    assert error.value.status_code == 413
    assert manager.storages[StorageBackend.ftp].adapter.content == b""
    assert manager.bulkheads[CATEGORY].borrowed_tokens == 0
