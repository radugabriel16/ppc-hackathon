import io
import time
import uuid

import anyio
import pytest

from app.models.enums import FileCategory, StorageBackend
from app.storage.base import CircuitOpen, StorageTimeout, StorageUnavailable, StoredObject
from app.storage.resilience import ManagedStorage

pytestmark = pytest.mark.anyio
CATEGORY = FileCategory.OUTAGE_RECORD


class Adapter:
    def __init__(self):
        self.fail = False
        self.delay = 0
        self.closed = False
        self.content = b""

    def put(self, key, stream, size):
        time.sleep(self.delay)
        self.content = stream.read()
        if self.fail:
            raise OSError("backend unavailable after consuming the stream")
        return StoredObject(key, size)

    def get(self, key):
        try:
            yield b"first"
            if self.fail:
                raise OSError("connection lost during download")
            yield b"second"
        finally:
            self.closed = True

    def delete(self, key):
        pass

    def health(self):
        return "ok"


async def test_circuit_half_open_allows_one_probe_and_recovers():
    adapter = Adapter()
    adapter.fail = True
    storage = ManagedStorage(StorageBackend.ftp, adapter, failure_threshold=1, reset_seconds=60)
    key = str(uuid.uuid4())
    with pytest.raises(StorageUnavailable):
        await storage.put(CATEGORY, key, io.BytesIO(b"abc"), 3)
    with pytest.raises(CircuitOpen):
        await storage.put(CATEGORY, key, io.BytesIO(b"abc"), 3)

    storage.breaker.opened_at -= 61
    generation = storage.breaker.before_call()
    assert storage.breaker.state == "half-open"
    with pytest.raises(CircuitOpen):
        storage.breaker.before_call()
    storage.breaker.failure(generation)
    assert storage.breaker.state == "open"

    storage.breaker.opened_at -= 61
    adapter.fail = False
    await storage.put(CATEGORY, key, io.BytesIO(b"abc"), 3)
    assert storage.breaker.state == "closed"
    assert storage.breaker.failures == 0


async def test_late_success_does_not_close_a_tripped_circuit():
    storage = ManagedStorage(StorageBackend.ftp, Adapter(), failure_threshold=1)
    old_generation = storage.breaker.before_call()
    storage.breaker.failure(old_generation)
    storage.breaker.success(old_generation)
    assert storage.breaker.state == "open"


async def test_timeout_keeps_capacity_and_stream_until_worker_exits():
    adapter = Adapter()
    adapter.delay = 0.05
    storage = ManagedStorage(
        StorageBackend.ftp, adapter, timeout=0.01, concurrency=1, failure_threshold=1
    )
    stream = io.BytesIO(b"payload")
    with pytest.raises(StorageTimeout):
        await storage.put(CATEGORY, str(uuid.uuid4()), stream, 7)
    assert stream.tell() == 0
    assert adapter.content == b""
    assert storage.limiter.borrowed_tokens == 0
    assert storage.breaker.state == "open"


async def test_download_errors_trip_circuit_and_close_stream():
    adapter = Adapter()
    adapter.fail = True
    storage = ManagedStorage(StorageBackend.ftp, adapter, failure_threshold=1)
    with pytest.raises(StorageUnavailable):
        async for _ in storage.get(CATEGORY, str(uuid.uuid4())):
            pass
    assert adapter.closed
    assert storage.breaker.state == "open"
    assert storage.limiter.borrowed_tokens == 0


async def test_caller_cancellation_releases_capacity_without_tripping_circuit():
    adapter = Adapter()
    adapter.delay = 0.05
    storage = ManagedStorage(StorageBackend.ftp, adapter, concurrency=1)
    with anyio.move_on_after(0.01) as scope:
        await storage.put(CATEGORY, str(uuid.uuid4()), io.BytesIO(b"x"), 1)
    assert scope.cancel_called
    assert storage.limiter.borrowed_tokens == 0
    assert storage.breaker.state == "closed"


async def test_open_download_keeps_storage_capacity_until_closed():
    adapter = Adapter()
    storage = ManagedStorage(StorageBackend.ftp, adapter, concurrency=1, timeout=1)
    first_chunk = anyio.Event()
    release = anyio.Event()
    written = anyio.Event()

    async def download():
        iterator = storage.get(CATEGORY, str(uuid.uuid4()))
        try:
            assert await anext(iterator) == b"first"
            first_chunk.set()
            await release.wait()
        finally:
            await iterator.aclose()

    async def upload():
        await storage.put(CATEGORY, str(uuid.uuid4()), io.BytesIO(b"x"), 1)
        written.set()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(download)
        await first_chunk.wait()
        tasks.start_soon(upload)
        await anyio.sleep(0.01)
        assert not written.is_set()
        release.set()
    assert written.is_set()
    assert adapter.closed


async def test_download_can_be_finalized_by_another_task():
    adapter = Adapter()
    storage = ManagedStorage(StorageBackend.ftp, adapter, concurrency=1)
    iterator = storage.get(CATEGORY, str(uuid.uuid4()))
    assert await anext(iterator) == b"first"

    async def close():
        await iterator.aclose()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(close)
    assert adapter.closed
    await storage.put(CATEGORY, str(uuid.uuid4()), io.BytesIO(b"x"), 1)
