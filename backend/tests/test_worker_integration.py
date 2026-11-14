import hashlib
import asyncio
import io
import smtplib
import socketserver
import threading
import uuid
from datetime import timedelta
from types import SimpleNamespace

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.metrics import INTEGRITY_FAILURES_TOTAL, METER_READINGS_MISSING
from app.core.settings import get_settings
from app.documents.encryption import DocumentKey
from app.jobs.maintenance import integrity_scrub, reconcile_files
from app.jobs.meter_gaps import count_gaps, detect_meter_gaps
from app.jobs.reminders import period_start, send_reminders
from app.jobs.orphans import delete_orphan_contents
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType
from app.models.enums import FileCategory, FileStatus, IssueStatus, StorageBackend
from app.models.files import File
from app.models.geography import NetworkAsset
from app.models.inspections import VideoInspection
from app.models.issues import MapIssue
from app.models.maintenance import MeterGap, ReminderDelivery, WorkerState
from app.models.metering import Meter, MeterReading
from app.uploads.service import now

pytestmark = pytest.mark.integration


@pytest.fixture
def worker_data(policy_manager, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "worker_batch_size", 1000)
    monkeypatch.setattr(settings, "integrity_scrub_bytes_per_second", 1024**3)
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    files, meters, issues, cases = [], [], [], []
    with Session(get_catalog_engine()) as db:
        saved_maintenance = {
            model: [
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in db.scalars(select(model))
            ]
            for model in (WorkerState, ReminderDelivery, MeterGap)
        }
        for model in saved_maintenance:
            db.execute(delete(model))
        asset = db.scalar(select(NetworkAsset).order_by(NetworkAsset.id))
        asset_id, region_id = asset.id, asset.region_id
        # Keep unrelated pre-existing demo files outside the scrub's due set.
        saved = db.execute(select(File.id, File.last_verified_at)).all()
        for file in db.scalars(select(File)):
            file.last_verified_at = now()
        db.commit()

    async def create_file(backend=StorageBackend.s3, status=FileStatus.READY, content=b"original", stored=None):
        file_id = uuid.uuid4()
        files.append((file_id, backend))
        await policy_manager.storages[backend].put(
            FileCategory.DRONE_VIDEO, str(file_id), io.BytesIO(content if stored is None else stored),
            len(content if stored is None else stored),
        )
        with Session(get_catalog_engine()) as db:
            db.add(File(
                id=file_id, region_id=region_id, category=FileCategory.DRONE_VIDEO,
                original_name="worker-test.bin", media_type="application/octet-stream",
                size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                storage_backend=backend, storage_locator=str(file_id), fallback_used=False,
                status=status, encrypted=False, created_at=now() - timedelta(hours=2),
            ))
            db.flush()
            if status == FileStatus.VERIFYING:
                db.add(VideoInspection(file_id=file_id, asset_id=asset_id, recorded_at=now()))
            db.commit()
        return file_id

    yield SimpleNamespace(
        manager=policy_manager, key=DocumentKey.load(settings), create_file=create_file,
        files=files, meters=meters, issues=issues, asset_id=asset_id, region_id=region_id,
        cases=cases,
    )
    for file_id, backend in files:
        policy_manager.storages[backend].adapter.delete(str(file_id))
    with Session(get_catalog_engine()) as db:
        ids = [row[0] for row in files]
        db.execute(delete(MeterGap).where(MeterGap.meter_id.in_(meters)))
        db.execute(delete(MeterReading).where(MeterReading.meter_id.in_(meters)))
        db.execute(delete(Meter).where(Meter.id.in_(meters)))
        db.execute(delete(VideoInspection).where(VideoInspection.file_id.in_(ids)))
        db.execute(delete(ClientDocument).where(ClientDocument.case_id.in_(cases)))
        db.execute(delete(ConnectionCase).where(ConnectionCase.id.in_(cases)))
        db.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(ids)))
        db.execute(delete(File).where(File.id.in_(ids)))
        db.execute(delete(MapIssue).where(MapIssue.id.in_(issues)))
        for model, rows in saved_maintenance.items():
            db.execute(delete(model))
            db.add_all(model(**row) for row in rows)
        for file_id, verified_at in saved:
            file = db.get(File, file_id)
            if file is not None:
                file.last_verified_at = verified_at
        db.commit()


async def two_workers(job, *args):
    async with anyio.create_task_group() as group:
        group.start_soon(job, *args)
        group.start_soon(job, *args)


def reset_job(name):
    with Session(get_catalog_engine()) as db:
        db.execute(delete(WorkerState).where(WorkerState.name == name))
        db.commit()


@pytest.mark.anyio
@pytest.mark.parametrize("backend", list(StorageBackend))
@pytest.mark.parametrize("corrupt", [False, True])
async def test_scrub_backends_idempotent_and_two_workers(worker_data, backend, corrupt):
    data = worker_data
    file_id = await data.create_file(backend, stored=b"tampered" if corrupt else None)
    metric = INTEGRITY_FAILURES_TOTAL.labels(category="DRONE_VIDEO", storage=backend.value)
    before = metric._value.get()
    await two_workers(integrity_scrub, data.manager, data.key)
    await integrity_scrub(data.manager, data.key)
    with Session(get_catalog_engine()) as db:
        file = db.get(File, file_id)
        assert file.status == (FileStatus.CORRUPT if corrupt else FileStatus.READY)
        assert file.last_verified_at is not None
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == file_id, AuditEvent.action == "FILE_INTEGRITY_FAILED",
        )) == int(corrupt)
    assert metric._value.get() == before + int(corrupt)


@pytest.mark.anyio
async def test_reconciler_ready_failed_cleanup_and_live_upload_lock(worker_data):
    data = worker_data
    staging = await data.create_file(status=FileStatus.STAGING)
    verifying = await data.create_file(status=FileStatus.VERIFYING)
    recent = await data.create_file(status=FileStatus.STAGING)
    locked = await data.create_file(status=FileStatus.STAGING)
    with Session(get_catalog_engine()) as db:
        db.get(File, recent).created_at = now()
        db.commit()
    from app.uploads.locking import upload_lock
    async with upload_lock(locked):
        await two_workers(reconcile_files, data.manager, data.key)
    await reconcile_files(data.manager, data.key)
    with Session(get_catalog_engine()) as db:
        failed = db.get(File, staging)
        assert failed.status == FileStatus.FAILED and failed.cleaned_at is not None
        assert failed.failure_reason == "STAGING_ABANDONED_METADATA_UNAVAILABLE"
        assert failed.maintenance_attempts == 1
        assert db.get(File, verifying).status == FileStatus.READY
        assert db.get(File, recent).status == FileStatus.STAGING
        assert db.get(File, locked).status == FileStatus.STAGING
    from app.storage.base import StorageNotFound
    with pytest.raises(StorageNotFound):
        list(data.manager.storages[StorageBackend.s3].adapter.get(str(staging)))


@pytest.mark.anyio
async def test_scrub_and_reconcile_respect_batch_limit(worker_data, monkeypatch):
    data = worker_data
    monkeypatch.setattr(get_settings(), "worker_batch_size", 1)
    ready = [await data.create_file() for _ in range(2)]
    staging = [await data.create_file(status=FileStatus.STAGING) for _ in range(2)]
    await integrity_scrub(data.manager, data.key)
    await reconcile_files(data.manager, data.key)
    with Session(get_catalog_engine()) as db:
        assert db.scalar(select(func.count()).select_from(File).where(
            File.id.in_(ready), File.last_verified_at.is_not(None),
        )) == 1
        assert db.scalar(select(func.count()).select_from(File).where(
            File.id.in_(staging), File.status == FileStatus.FAILED,
        )) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("backend", list(StorageBackend))
async def test_orphan_inventory_keeps_referenced_and_recent_two_workers(worker_data, backend, monkeypatch):
    from app.storage.base import InventoryObject, InventoryPage, StorageNotFound

    data = worker_data
    retained = await data.create_file(backend)
    orphan, recent = uuid.uuid4(), uuid.uuid4()
    storage = data.manager.storages[backend]
    for file_id in (orphan, recent):
        storage.adapter.put(str(file_id), io.BytesIO(b"orphan"), 6)
    original = storage.inventory

    async def aged(*args):
        page = await original(*args)
        return InventoryPage([
            InventoryObject(
                item.key, now() - timedelta(hours=1) if item.key in {str(orphan), str(retained)}
                else item.modified_at,
            ) for item in page.objects
        ], page.next_cursor)

    monkeypatch.setattr(storage, "inventory", aged)
    try:
        await two_workers(delete_orphan_contents, data.manager)
        await delete_orphan_contents(data.manager)
        with pytest.raises(StorageNotFound):
            list(storage.adapter.get(str(orphan)))
        assert b"".join(storage.adapter.get(str(recent))) == b"orphan"
        assert b"".join(storage.adapter.get(str(retained))) == b"original"
    finally:
        for file_id in (orphan, recent):
            storage.adapter.delete(str(file_id))


@pytest.mark.anyio
async def test_reconcile_transient_failure_retries_then_terminal(worker_data, monkeypatch):
    data = worker_data
    file_id = await data.create_file(status=FileStatus.VERIFYING)
    storage = data.manager.storages[StorageBackend.s3]
    original = storage.get

    async def unavailable(*args):
        from app.storage.base import StorageUnavailable
        raise StorageUnavailable("temporary outage")
        yield

    monkeypatch.setattr(storage, "get", unavailable)
    for attempt in range(1, get_settings().worker_max_attempts + 1):
        reset_job("reconcile_files")
        with Session(get_catalog_engine()) as db:
            db.get(File, file_id).maintenance_at = None
            db.commit()
        await two_workers(reconcile_files, data.manager, data.key)
        with Session(get_catalog_engine()) as db:
            file = db.get(File, file_id)
            assert file.maintenance_attempts == attempt
            assert file.status == (
                FileStatus.FAILED if attempt == get_settings().worker_max_attempts else FileStatus.VERIFYING
            )
    monkeypatch.setattr(storage, "get", original)
    with Session(get_catalog_engine()) as db:
        assert db.get(File, file_id).failure_reason == "VERIFY_RETRIES_EXHAUSTED"


@pytest.mark.anyio
async def test_meter_gaps_active_stale_backfill_and_zero(worker_data):
    data = worker_data
    checked_at = now()
    with Session(get_catalog_engine()) as db:
        for active in (True, False):
            meter_id = uuid.uuid4()
            data.meters.append(meter_id)
            db.add(Meter(id=meter_id, external_code=f"worker-{meter_id}", asset_id=data.asset_id))
        db.commit()
    for meter_id, age in zip(data.meters, (0, 3600)):
        for seq, minutes in ((1, 4), (3, 2)):
            file_id = await data.create_file(StorageBackend.db)
            with Session(get_catalog_engine()) as db:
                db.add(MeterReading(
                    meter_id=meter_id, file_id=file_id, reading_key=str(uuid.uuid4()),
                    seq=seq, interval_start=checked_at - timedelta(minutes=minutes),
                    interval_end=checked_at - timedelta(minutes=minutes - 1),
                    energy_kwh=1, received_at=checked_at - timedelta(seconds=age),
                ))
                db.commit()
    await two_workers(detect_meter_gaps)
    with Session(get_catalog_engine()) as db:
        assert db.get(MeterGap, data.meters[0]).missing == 1
        assert db.get(MeterGap, data.meters[1]).missing == 0
        for meter_id in data.meters:
            db.get(MeterGap, meter_id).active_until = now() - timedelta(seconds=1)
        db.commit()
    # A skipped sampling run must still expire metrics on every replica.
    await detect_meter_gaps()
    from app.models.geography import Region
    with Session(get_catalog_engine()) as db:
        region = db.get(Region, data.region_id).code
    assert METER_READINGS_MISSING.labels(region=region)._value.get() == 0
    assert b"filegrid_meter_readings_missing" in TestClient(create_app()).get("/metrics").content


def test_interval_and_sequence_gaps_not_double_counted():
    at = now()
    readings = [
        SimpleNamespace(seq=1, interval_start=at, interval_end=at + timedelta(minutes=1)),
        SimpleNamespace(seq=3, interval_start=at + timedelta(minutes=2), interval_end=at + timedelta(minutes=3)),
    ]
    assert count_gaps(readings) == 1
    readings[1].seq = 2
    assert count_gaps(readings) == 1
    assert count_gaps([]) == 0


@pytest.fixture
def fake_smtp(monkeypatch):
    messages = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 fake smtp\r\n")
            data = None
            for line in self.rfile:
                if data is not None:
                    if line == b".\r\n":
                        messages.append(b"".join(data))
                        data = None
                        self.wfile.write(b"250 accepted\r\n")
                    else:
                        data.append(line)
                elif line.upper().startswith(b"DATA"):
                    data = []
                    self.wfile.write(b"354 end with dot\r\n")
                elif line.upper().startswith(b"QUIT"):
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        monkeypatch.setattr(get_settings(), "smtp_port", server.server_address[1])
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield messages
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.anyio
async def test_reminders_fake_smtp_dedupe_two_workers_and_next_period(worker_data, fake_smtp, monkeypatch):
    data = worker_data
    with Session(get_catalog_engine()) as db:
        for status, age in ((IssueStatus.OPEN, 48), (IssueStatus.RESOLVED, 48), (IssueStatus.OPEN, 0)):
            issue_id = uuid.uuid4()
            data.issues.append(issue_id)
            db.add(MapIssue(
                id=issue_id, asset_id=data.asset_id, location="SRID=4326;POINT(26 44)",
                severity="LOW", status=status, created_at=now() - timedelta(hours=age), version=1,
            ))
        db.commit()
    await two_workers(send_reminders)
    count = len(fake_smtp)
    assert count > 0
    assert any(str(data.issues[0]).encode() in message for message in fake_smtp)
    assert not any(str(issue).encode() in message for issue in data.issues[1:] for message in fake_smtp)
    with Session(get_catalog_engine()) as db:
        assert db.scalar(select(func.count()).select_from(ReminderDelivery).where(
            ReminderDelivery.kind == "checklist", ReminderDelivery.status == "SENT",
        )) > 0
    reset_job("reminders")
    await send_reminders()
    assert len(fake_smtp) == count
    next_day = now() + timedelta(hours=get_settings().reminder_period_hours)
    monkeypatch.setattr("app.jobs.reminders.now", lambda: next_day)
    reset_job("reminders")
    await send_reminders()
    assert len(fake_smtp) > count


@pytest.mark.anyio
async def test_reminder_smtp_failure_is_recorded_not_repeated(worker_data, monkeypatch):
    calls = []

    def reject(*args, **kwargs):
        calls.append(1)
        raise smtplib.SMTPConnectError(421, "unavailable")

    monkeypatch.setattr("app.jobs.reminders.smtplib.SMTP", reject)
    await send_reminders()
    attempts = len(calls)
    assert attempts > 0
    reset_job("reminders")
    await send_reminders()
    assert len(calls) == attempts
    with Session(get_catalog_engine()) as db:
        assert db.scalar(select(func.count()).select_from(ReminderDelivery).where(
            ReminderDelivery.period_start == period_start(now()), ReminderDelivery.status == "FAILED",
        )) == attempts


@pytest.mark.anyio
async def test_reminders_skip_closed_and_complete_checklists(worker_data, fake_smtp):
    data = worker_data
    with Session(get_catalog_engine()) as db:
        client_id = db.scalar(select(Client.id).limit(1))
        required = list(db.scalars(select(DocumentType.id).where(
            DocumentType.required_for_connection.is_(True),
        )))
        for status in ("OPEN", "CLOSED", "OPEN"):
            case_id = uuid.uuid4()
            data.cases.append(case_id)
            db.add(ConnectionCase(
                id=case_id, client_id=client_id, status=status, opened_at=now(),
            ))
        db.commit()
    for type_id in required:
        file_id = await data.create_file()
        with Session(get_catalog_engine()) as db:
            db.add(ClientDocument(
                case_id=data.cases[2], document_type_id=type_id,
                file_id=file_id, uploaded_at=now(),
            ))
            db.commit()
    await two_workers(send_reminders)
    assert any(str(data.cases[0]).encode() in message for message in fake_smtp)
    assert not any(
        str(case_id).encode() in message for case_id in data.cases[1:] for message in fake_smtp
    )


@pytest.mark.anyio
async def test_worker_schedules_independently_and_joins_cancelled_jobs(monkeypatch):
    from app.jobs import worker
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    counts = {"slow": 0, "quick": 0, "cancelled": 0}
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(worker, "tracer", provider.get_tracer("test-worker"))

    async def slow():
        counts["slow"] += 1
        try:
            await asyncio.Event().wait()
        finally:
            counts["cancelled"] += 1

    async def quick():
        counts["quick"] += 1

    monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(worker, "worker_jobs", lambda *_: (
        ("slow", slow, ()), ("quick", quick, ()),
    ))
    task = asyncio.create_task(worker.run_worker_loop(None, None))
    try:
        with anyio.fail_after(2):
            while counts["quick"] < 2:
                await anyio.sleep(0.01)
        assert counts["slow"] == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        provider.shutdown()
    assert counts["cancelled"] == 1
    spans = exporter.get_finished_spans()
    assert sum(span.name == "worker.quick" for span in spans) >= 2
    assert sum(span.name == "worker.slow" for span in spans) == 1
