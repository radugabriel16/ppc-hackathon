import hashlib
import itertools
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.security import get_simulator_token, sign_session_id
from app.core.db import get_catalog_db, get_catalog_engine, get_storage_engine
from app.core.metrics import METER_INGEST_TOTAL, REQUESTS_REJECTED_TOTAL
from app.core.settings import get_settings
from app.main import create_app
from app.models.auth import AppUser, UserSession
from app.models.enums import FileCategory, FileStatus, StorageBackend
from app.models.files import File
from app.models.geography import NetworkAsset
from app.models.metering import Meter, MeterReading

pytestmark = pytest.mark.integration
PATH = "/api/v1/meter-readings"
CATEGORY = FileCategory.METER_READING


@pytest.fixture
def api(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "role", "ingest")
    app = create_app()
    attempted_ids = []
    current_db = ContextVar("metering_test_db")
    session_id = uuid.uuid4()
    with Session(get_catalog_engine()) as db:
        meter = db.scalars(select(Meter).order_by(Meter.external_code)).first()
        meter_id, code = meter.id, meter.external_code
        user = db.scalar(select(AppUser).where(AppUser.username == "operator"))
        db.add(UserSession(
            id=session_id, user_id=user.id, csrf_token=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.commit()
    counter = itertools.count()
    start = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=uuid.uuid4().int % 1_000_000_000
    )

    def payload():
        interval = start + timedelta(minutes=next(counter))
        iso = interval.isoformat().replace("+00:00", "Z")
        return {
            "meterExternalCode": code, "readingKey": f"{code}:{iso}", "seq": 1,
            "intervalStart": iso, "intervalEnd": (interval + timedelta(minutes=15)).isoformat(),
            "energyKwh": 3.42,
        }

    async def tracked_db():
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            token = current_db.set(db)
            try:
                yield db
            finally:
                current_db.reset(token)

    app.dependency_overrides[get_catalog_db] = tracked_db
    try:
        with TestClient(
            app, base_url=str(settings.app_origin).rstrip("/"),
            headers={"Authorization": f"Bearer {get_simulator_token()}"},
            raise_server_exceptions=False,
        ) as client:
            storage = app.state.policy_manager.storages[StorageBackend.db]
            original_put, original_delete = storage.put, storage.delete

            async def put(category, key, stream, size):
                assert not current_db.get().in_transaction()
                attempted_ids.append(uuid.UUID(key))
                return await original_put(category, key, stream, size)

            async def discard(category, key):
                assert not current_db.get().in_transaction()
                return await original_delete(category, key)

            monkeypatch.setattr(storage, "put", put)
            monkeypatch.setattr(storage, "delete", discard)
            yield client, app.state.policy_manager, payload, meter_id, attempted_ids, session_id
    finally:
        with Session(get_catalog_engine()) as db:
            db.execute(delete(MeterReading).where(MeterReading.file_id.in_(attempted_ids)))
            db.execute(delete(File).where(File.id.in_(attempted_ids)))
            db.execute(delete(UserSession).where(UserSession.id == session_id))
            db.commit()
        with get_storage_engine().begin() as connection:
            for file_id in attempted_ids:
                connection.execute(
                    text("DELETE FROM file_contents WHERE file_id = :id"), {"id": file_id}
                )


def stored_attempts(ids):
    with get_storage_engine().connect() as connection:
        return {
            file_id for file_id in ids if connection.execute(
                text("SELECT 1 FROM file_contents WHERE file_id = :id"), {"id": file_id}
            ).scalar_one_or_none()
        }


def test_exact_bytes_idempotency_atomic_catalog_and_metrics(api):
    client, _, payload, meter_id, ids, _ = api
    body = payload()
    raw = (json.dumps(body, indent=2) + "\r\n").encode()
    counters = {
        result: METER_INGEST_TOTAL.labels(result=result)._value.get()
        for result in ("created", "duplicate", "conflict")
    }
    new = client.post(PATH + "/ingest", content=raw)
    assert new.status_code == 201, new.text
    duplicate = client.post(PATH + "/ingest", content=raw)
    assert duplicate.status_code == 200 and duplicate.json() == new.json()
    # Even formatting-only changes are different original payload bytes.
    assert client.post(PATH + "/ingest", json=body).status_code == 409
    assert client.post(PATH + "/ingest", json={**body, "energyKwh": 99}).status_code == 409
    assert len(ids) == 1
    with Session(get_catalog_engine()) as db:
        row = db.get(MeterReading, uuid.UUID(new.json()["id"]))
        file = db.get(File, row.file_id)
        region = db.scalar(select(NetworkAsset.region_id).join(
            Meter, Meter.asset_id == NetworkAsset.id
        ).where(Meter.id == meter_id))
        assert row.energy_kwh == Decimal("3.42")
        assert file.region_id == region and file.status == FileStatus.READY
        assert file.category == CATEGORY and file.storage_backend == StorageBackend.db
        assert file.sha256 == hashlib.sha256(raw).hexdigest()
        assert file.size_bytes == len(raw) and file.uploaded_by is None
    with get_storage_engine().connect() as connection:
        stored = connection.execute(
            text("SELECT content FROM file_contents WHERE file_id = :id"), {"id": file.id}
        ).scalar_one()
        assert bytes(stored) == raw
    for result, count in (("created", 1), ("duplicate", 1), ("conflict", 2)):
        assert METER_INGEST_TOTAL.labels(result=result)._value.get() == counters[result] + count


@pytest.mark.parametrize("conflicting", [False, True])
def test_twenty_concurrent_deliveries_resolve_unique_violation(api, monkeypatch, conflicting):
    client, manager, payload, meter_id, ids, _ = api
    body = payload()
    storage = manager.storages[StorageBackend.db]
    original = storage.adapter.put
    barrier = threading.Barrier(20, timeout=30)

    def synchronized_put(*args):
        barrier.wait()
        return original(*args)

    monkeypatch.setattr(storage.adapter, "put", synchronized_put)

    def post(index):
        return client.post(PATH + "/ingest", json={
            **body, "energyKwh": index if conflicting else body["energyKwh"],
        })

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(post, range(20)))
    statuses = [response.status_code for response in responses]
    assert statuses.count(201) == 1, statuses
    assert statuses.count(409 if conflicting else 200) == 19, statuses
    with Session(get_catalog_engine()) as db:
        rows = db.scalars(select(MeterReading).where(
            MeterReading.meter_id == meter_id, MeterReading.reading_key == body["readingKey"],
        )).all()
        assert len(rows) == 1
        assert db.scalar(select(func.count()).select_from(File).where(File.id.in_(ids))) == 1
        assert stored_attempts(ids) == {rows[0].file_id}


@pytest.mark.parametrize("change", [
    {"energyKwh": -1}, {"energyKwh": "NaN"}, {"seq": 2**31}, {"seq": True},
    {"readingKey": "unrelated"}, {"intervalStart": "2026-01-01T00:00:00"},
    {"intervalEnd": "1999-01-01T00:00:00Z"},
    {
        "meterExternalCode": "unknown", "readingKey": "unknown:2026-01-01T00:00:00Z",
        "intervalStart": "2026-01-01T00:00:00Z", "intervalEnd": "2026-01-01T00:15:00Z",
    },
])
def test_invalid_readings_do_not_write(api, change):
    client, _, payload, _, ids, _ = api
    response = client.post(PATH + "/ingest", json={**payload(), **change})
    assert response.status_code == 422, response.text
    assert response.json()["code"] and response.json()["requestId"]
    assert ids == []


def test_bounded_body_malformed_json_and_bulkhead(api):
    client, manager, payload, _, ids, _ = api
    policy = manager.config.categories[CATEGORY]
    policy.max_size_bytes = 512
    assert client.post(PATH + "/ingest", content=iter([b" " * 300] * 2)).status_code == 413
    assert client.post(PATH + "/ingest", content=b"{broken").status_code == 422
    assert client.post(PATH + "/ingest", json=[]).status_code == 422
    limiter = manager.bulkheads[CATEGORY]
    limiter.total_tokens = 1
    borrower = object()

    async def hold():
        limiter.acquire_on_behalf_of_nowait(borrower)

    client.portal.call(hold)
    before = REQUESTS_REJECTED_TOTAL.labels(category=CATEGORY.value, reason="bulkhead")._value.get()
    try:
        response = client.post(PATH + "/ingest", json=payload())
        assert response.status_code == 503 and response.headers["Retry-After"] == "1"
        assert REQUESTS_REJECTED_TOTAL.labels(
            category=CATEGORY.value, reason="bulkhead"
        )._value.get() == before + 1
    finally:
        client.portal.call(limiter.release_on_behalf_of, borrower)
    assert ids == []


def test_auth_separation_and_filtered_capped_listing(api):
    client, _, payload, meter_id, _, session_id = api
    assert client.get(PATH).status_code == 401
    first = client.post(PATH + "/ingest", json=payload()).json()
    second = client.post(PATH + "/ingest", json=payload()).json()
    for token in ("", "Bearer invalid", "Basic invalid"):
        assert client.post(
            PATH + "/ingest", json=payload(), headers={"Authorization": token},
        ).status_code == 401
    client.cookies.set(get_settings().session_cookie_name, sign_session_id(session_id))
    assert client.post(
        PATH + "/ingest", json=payload(), headers={"Authorization": ""},
    ).status_code == 401
    response = client.get(PATH, params={
        "meterId": str(meter_id), "from": first["intervalEnd"], "to": second["intervalEnd"],
        "size": 100000,
    })
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["size"] == 100 and page["totalElements"] == 2 and page["totalPages"] == 1
    assert [row["id"] for row in page["items"]] == [second["id"], first["id"]]
    assert client.get(PATH, params={"meterId": str(uuid.uuid4())}).json()["items"] == []
    assert client.get(PATH, params={"page": 1000000}).json()["items"] == []
    assert client.get(PATH, params={"from": second["intervalEnd"], "to": first["intervalEnd"]}).status_code == 422


def test_failed_catalog_commit_rolls_back_both_rows_and_discards_bytes(api, monkeypatch):
    client, _, payload, _, ids, _ = api

    def fail(_):
        raise SQLAlchemyError("Injected catalog commit failure")

    monkeypatch.setattr(Session, "commit", fail)
    try:
        response = client.post(PATH + "/ingest", json=payload())
        assert response.status_code == 500
        with Session(get_catalog_engine()) as db:
            assert db.scalar(select(func.count()).select_from(File).where(File.id.in_(ids))) == 0
        assert stored_attempts(ids) == set()
    finally:
        monkeypatch.undo()


def test_unavailable_storage_and_timeout_after_write_leave_no_catalog_rows(api, monkeypatch):
    client, manager, payload, _, ids, _ = api
    adapter = manager.storages[StorageBackend.db].adapter
    original = adapter.put

    def fail(*args):
        original(*args)
        raise TimeoutError("Write committed but acknowledgement timed out")

    monkeypatch.setattr(adapter, "put", fail)
    response = client.post(PATH + "/ingest", json=payload())
    assert response.status_code == 503 and response.headers["Retry-After"] == "1"
    assert stored_attempts(ids) == set()
    with Session(get_catalog_engine()) as db:
        assert db.scalar(select(func.count()).select_from(File).where(File.id.in_(ids))) == 0
