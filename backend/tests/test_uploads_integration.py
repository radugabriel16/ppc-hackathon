import hashlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_catalog_db, get_catalog_engine, get_storage_engine
from app.core.metrics import (
    FILE_TIME_TO_AVAILABLE_SECONDS,
    INTEGRITY_FAILURES_TOTAL,
    UPLOAD_SESSIONS_ACTIVE,
    UPLOAD_SESSIONS_STALLED,
)
from app.core.settings import get_settings
from app.jobs.orphans import delete_orphan_contents
from app.jobs.worker import expire_upload, run_worker_once, update_upload_metrics, verify_upload
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.enums import FileCategory, FileStatus, StorageBackend
from app.models.files import File
from app.models.inspections import VideoInspection
from app.models.uploads import UploadPart, UploadSession
from app.storage.base import StorageUnavailable
from app.uploads.service import now

pytestmark = pytest.mark.integration
BASE = "/api/v1"
CATEGORY = FileCategory.DRONE_VIDEO


@pytest.fixture
def api(monkeypatch):
    settings = get_settings()
    app = create_app()
    run_id = f"step8-{uuid.uuid4().hex}"
    session_ids = []
    current_db = ContextVar("upload_test_db", default=None)

    async def tracked_db():
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            token = current_db.set(db)
            try:
                yield db
            finally:
                current_db.reset(token)

    app.dependency_overrides[get_catalog_db] = tracked_db
    with TestClient(
        app, base_url=str(settings.app_origin).rstrip("/"),
        headers={"Origin": str(settings.app_origin).rstrip("/"), "X-Request-Id": run_id},
        raise_server_exceptions=False,
    ) as client:
        manager = app.state.policy_manager
        manager.config.categories[CATEGORY].chunk_size_bytes = 5 * 1024 * 1024
        storage = manager.storages[StorageBackend.s3]
        for operation in ("create_multipart", "upload_part", "complete_multipart", "abort_multipart", "delete"):
            original = getattr(storage, operation)

            async def wrapped(*args, original=original, **kwargs):
                db = current_db.get()
                assert db is None or not db.in_transaction()
                return await original(*args, **kwargs)

            monkeypatch.setattr(storage, operation, wrapped)

        def login(username="operator"):
            response = client.post(BASE + "/auth/login", json={
                "username": username,
                "password": (Path(settings.secrets_dir) / f"{username}_password").read_text().strip(),
            })
            assert response.status_code == 200, response.text
            session_ids.append(uuid.UUID(client.cookies[settings.session_cookie_name].split(".")[0]))
            client.headers["X-CSRF-Token"] = client.cookies["filegrid_csrf"]

        login()
        asset = client.get(BASE + "/assets").json()["items"][0]

        def create(size, digest=None, **changes):
            body = {
                "category": CATEGORY.value, "fileName": f"{run_id}.bin", "sizeBytes": size,
                "sha256": digest, "metadata": {
                    "category": CATEGORY.value, "assetId": asset["id"],
                    "regionId": asset["regionId"], "recordedAt": "2026-01-01T10:00:00Z",
                },
                **changes,
            }
            return client.post(BASE + "/uploads", json=body)

        def part(upload_id, number, content, digest=None):
            return client.put(f"{BASE}/uploads/{upload_id}/parts/{number}", content=content, headers={
                "Content-Type": "application/octet-stream",
                "X-Part-SHA256": digest or hashlib.sha256(content).hexdigest(),
            })

        try:
            yield client, manager, create, part, login
        finally:
            with Session(get_catalog_engine()) as db:
                uploads = db.scalars(select(UploadSession).where(
                    UploadSession.file_name == f"{run_id}.bin"
                )).all()
                snapshots = [
                    (upload.id, upload.file_id, upload.s3_upload_id, upload.category)
                    for upload in uploads
                ]
            for _, file_id, s3_id, category in snapshots:
                if s3_id:
                    storage.adapter.abort_multipart(str(file_id), s3_id)
                storage.adapter.delete(str(file_id))
            with Session(get_catalog_engine()) as db:
                ids = [row[1] for row in snapshots]
                db.execute(delete(UploadSession).where(UploadSession.id.in_([row[0] for row in snapshots])))
                db.execute(delete(VideoInspection).where(VideoInspection.file_id.in_(ids)))
                db.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(ids)))
                db.execute(delete(AuditEvent).where(AuditEvent.request_id == run_id))
                db.execute(delete(File).where(File.id.in_(ids)))
                db.execute(delete(UserSession).where(UserSession.id.in_(session_ids)))
                db.commit()
            with get_storage_engine().begin() as connection:
                for file_id in ids:
                    connection.execute(text("DELETE FROM file_contents WHERE file_id=:id"), {"id": file_id})


def test_resume_hashes_exact_sizes_duplicate_and_ready(api, monkeypatch):
    client, manager, create, part, _ = api
    first, last = b"a" * (5 * 1024 * 1024), b"last part\x00\r\n"
    content = first + last
    digest = hashlib.sha256(content).hexdigest()
    response = create(len(content), digest)
    assert response.status_code == 201, response.text
    upload = response.json()
    upload_id = upload["uploadId"]
    path = f"{BASE}/uploads/{upload_id}"
    assert upload["totalParts"] == 2 and upload["expiresAt"]
    assert client.post(path + "/complete", json={"sha256": digest}).status_code == 409
    assert part(upload_id, 0, first).status_code == 422
    assert part(upload_id, 3, last).status_code == 422
    assert part(upload_id, 1, first, "0" * 64).status_code == 422
    assert part(upload_id, 1, first[:-1]).status_code == 422
    assert part(upload_id, 1, first + b"x").status_code == 413
    assert client.get(path).json()["receivedParts"] == []

    result = part(upload_id, 1, first)
    assert result.status_code == 200, result.text
    assert client.get(path).json()["receivedParts"] == [1]
    original = manager.storages[StorageBackend.s3].upload_part
    calls = []

    async def record(*args):
        calls.append(args[3])
        return await original(*args)

    monkeypatch.setattr(manager.storages[StorageBackend.s3], "upload_part", record)
    assert part(upload_id, 1, first).json() == result.json()
    assert calls == []
    assert part(upload_id, 1, b"b" * len(first)).status_code == 422
    assert part(upload_id, 2, last).status_code == 200
    assert calls == [2]
    assert client.post(path + "/complete", json={"sha256": "0" * 64}).status_code == 422
    completed = client.post(path + "/complete", json={"sha256": digest})
    assert completed.status_code == 202, completed.text
    file_id = completed.json()["fileId"]
    assert completed.json()["status"] == "VERIFYING"
    assert client.post(path + "/complete", json={"sha256": digest}).json() == completed.json()
    assert part(upload_id, 1, first).status_code == 409
    assert client.delete(path).status_code == 409
    assert client.get(path).json() == {
        "status": "COMPLETED", "receivedParts": [1, 2], "totalParts": 2,
    }
    metric = FILE_TIME_TO_AVAILABLE_SECONDS.labels(category=CATEGORY.value)
    before = metric._sum.get()
    client.portal.call(verify_upload, uuid.UUID(upload_id), manager, client.app.state.document_key)
    file = client.get(f"{BASE}/files/{file_id}").json()
    assert file["status"] == "READY" and file["lastVerifiedAt"] and file["readyAt"]
    assert metric._sum.get() > before
    assert client.get(f"{BASE}/files/{file_id}/download").content == content
    with Session(get_catalog_engine()) as db:
        assert len(db.scalars(select(VideoInspection).where(
            VideoInspection.file_id == uuid.UUID(file_id)
        )).all()) == 1
        assert len(db.scalars(select(UploadPart).where(
            UploadPart.upload_id == uuid.UUID(upload_id)
        )).all()) == 2


@pytest.mark.parametrize("terminal", ["ABORTED", "EXPIRED"])
def test_backend_rejects_all_parts_after_abort_or_expiry(api, monkeypatch, terminal):
    client, manager, create, part, _ = api
    content = b"part"
    upload_id = create(len(content)).json()["uploadId"]
    path = f"{BASE}/uploads/{upload_id}"
    assert part(upload_id, 1, content).status_code == 200
    if terminal == "ABORTED":
        assert client.delete(path).status_code == 204
        assert client.delete(path).status_code == 204
    else:
        with Session(get_catalog_engine()) as db:
            db.get(UploadSession, uuid.UUID(upload_id)).expires_at = now() - timedelta(seconds=1)
            db.commit()

    async def forbidden(*args):
        pytest.fail("A closed/expired upload reached SeaweedFS upload_part")

    monkeypatch.setattr(manager.storages[StorageBackend.s3], "upload_part", forbidden)
    assert client.get(path).json()["status"] == terminal
    assert part(upload_id, 1, content).status_code == 409
    assert part(upload_id, 2, b"new").status_code == 409
    assert client.post(path + "/complete", json={
        "sha256": hashlib.sha256(content).hexdigest()
    }).status_code == 409
    if terminal == "EXPIRED":
        client.portal.call(expire_upload, uuid.UUID(upload_id), manager)
    with Session(get_catalog_engine()) as db:
        upload = db.get(UploadSession, uuid.UUID(upload_id))
        assert upload.status == terminal and upload.s3_upload_id is None
        assert db.get(File, upload.file_id).status == FileStatus.FAILED


def test_worker_rechecks_full_sha_marks_corrupt_and_audits(api):
    client, manager, create, part, _ = api
    content = b"not the declared whole-file hash"
    upload_id = create(len(content)).json()["uploadId"]
    assert part(upload_id, 1, content).status_code == 200
    completed = client.post(f"{BASE}/uploads/{upload_id}/complete", json={"sha256": "0" * 64})
    assert completed.status_code == 202
    file_id = completed.json()["fileId"]
    metric = INTEGRITY_FAILURES_TOTAL.labels(category=CATEGORY.value, storage="s3")
    before = metric._value.get()
    client.portal.call(verify_upload, uuid.UUID(upload_id), manager, client.app.state.document_key)
    assert metric._value.get() == before + 1
    assert client.get(f"{BASE}/files/{file_id}").json()["status"] == "CORRUPT"
    assert client.get(f"{BASE}/files/{file_id}/download").status_code == 409
    with Session(get_catalog_engine()) as db:
        assert db.scalar(select(AuditEvent).where(
            AuditEvent.entity_id == uuid.UUID(file_id),
            AuditEvent.action == "FILE_INTEGRITY_FAILED",
        )) is not None


@pytest.mark.parametrize("failure", ["storage_ack", "catalog"])
def test_worker_recovers_completion_after_ambiguous_s3_or_catalog_failure(api, monkeypatch, failure):
    client, manager, create, part, _ = api
    content = b"completion survives a crash"
    digest = hashlib.sha256(content).hexdigest()
    upload_id = create(len(content)).json()["uploadId"]
    assert part(upload_id, 1, content).status_code == 200
    if failure == "storage_ack":
        storage = manager.storages[StorageBackend.s3]
        original = storage.complete_multipart

        async def fail(*args):
            await original(*args)
            raise StorageUnavailable("lost completion acknowledgement")

        monkeypatch.setattr(storage, "complete_multipart", fail)
    else:
        from app.uploads import service
        original = service.link_inspection

        def fail(*args):
            raise SQLAlchemyError("catalog commit unavailable")

        monkeypatch.setattr(service, "link_inspection", fail)
    response = client.post(f"{BASE}/uploads/{upload_id}/complete", json={"sha256": digest})
    assert response.status_code == (503 if failure == "storage_ack" else 500), response.text
    assert part(upload_id, 1, content).status_code == 409
    if failure == "catalog":
        monkeypatch.setattr(service, "link_inspection", original)
    client.portal.call(run_worker_once, manager, client.app.state.document_key)
    client.portal.call(run_worker_once, manager, client.app.state.document_key)
    with Session(get_catalog_engine()) as db:
        upload = db.get(UploadSession, uuid.UUID(upload_id))
        assert upload.status == "COMPLETED"
        file_id = upload.file_id
        assert db.get(File, file_id).status == FileStatus.READY
    assert client.get(f"{BASE}/files/{file_id}/download").content == content


def test_failed_abort_is_terminal_immediately_and_worker_retries(api, monkeypatch):
    client, manager, create, part, _ = api
    upload_id = create(4).json()["uploadId"]
    storage = manager.storages[StorageBackend.s3]
    original = storage.abort_multipart

    async def fail(*args):
        raise StorageUnavailable("temporary abort failure")

    monkeypatch.setattr(storage, "abort_multipart", fail)
    response = client.delete(f"{BASE}/uploads/{upload_id}")
    assert response.status_code == 503 and response.headers["Retry-After"] == "1"
    assert part(upload_id, 1, b"part").status_code == 409
    monkeypatch.setattr(storage, "abort_multipart", original)
    client.portal.call(run_worker_once, manager, client.app.state.document_key)
    with Session(get_catalog_engine()) as db:
        upload = db.get(UploadSession, uuid.UUID(upload_id))
        assert upload.status == "ABORTED" and upload.s3_upload_id is None


def test_part_abort_race_uses_cross_connection_lock(api, monkeypatch):
    client, manager, create, part, _ = api
    upload_id = create(4).json()["uploadId"]
    entered, release = threading.Event(), threading.Event()
    storage = manager.storages[StorageBackend.s3]
    original = storage.adapter.upload_part

    def blocked(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(storage.adapter, "upload_part", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(part, upload_id, 1, b"part")
        try:
            assert entered.wait(10)
            busy = client.delete(f"{BASE}/uploads/{upload_id}")
            assert busy.status_code == 503 and busy.headers["Retry-After"] == "1"
        finally:
            release.set()
        assert future.result().status_code == 200
    assert client.delete(f"{BASE}/uploads/{upload_id}").status_code == 204
    assert part(upload_id, 1, b"part").status_code == 409


def test_auth_ownership_policy_and_bulkhead(api):
    client, manager, create, part, login = api
    metadata = {
        "category": CATEGORY.value, "assetId": str(uuid.uuid4()),
        "recordedAt": "2026-01-01T00:00:00Z",
    }
    assert create(4, metadata=metadata).status_code == 404
    metadata["regionId"] = str(uuid.uuid4())
    asset = client.get(BASE + "/assets").json()["items"][0]
    metadata["assetId"] = asset["id"]
    assert create(4, metadata=metadata).status_code == 422
    assert create(0).status_code == 422
    assert create(6 * 1024**3).status_code == 413
    assert create(4, category="CONNECTION_DOCUMENT").status_code == 422
    upload_id = create(4).json()["uploadId"]
    limiter = manager.bulkheads[CATEGORY]
    limiter.total_tokens = 1
    borrower = object()

    async def hold():
        limiter.acquire_on_behalf_of_nowait(borrower)

    client.portal.call(hold)
    try:
        for response in (part(upload_id, 1, b"part"), create(4)):
            assert response.status_code == 503 and response.headers["Retry-After"] == "1"
    finally:
        client.portal.call(limiter.release_on_behalf_of, borrower)
    token = client.headers.pop("X-CSRF-Token")
    assert part(upload_id, 1, b"part").status_code == 403
    client.headers["X-CSRF-Token"] = token
    login("manager")
    path = f"{BASE}/uploads/{upload_id}"
    assert client.get(path).status_code == 403
    assert part(upload_id, 1, b"part").status_code == 403
    assert client.post(path + "/complete", json={"sha256": "0" * 64}).status_code == 403
    assert client.delete(path).status_code == 403
    client.cookies.clear()
    assert client.get(path).status_code == 401
    assert create(4).status_code == 403


def test_session_gauges_count_stalled_and_exclude_expired(api):
    _, _, create, _, _ = api
    update_upload_metrics()
    active, stalled = UPLOAD_SESSIONS_ACTIVE._value.get(), UPLOAD_SESSIONS_STALLED._value.get()
    upload_id = uuid.UUID(create(4).json()["uploadId"])
    with Session(get_catalog_engine()) as db:
        db.get(UploadSession, upload_id).updated_at = now() - timedelta(minutes=11)
        db.commit()
    update_upload_metrics()
    assert UPLOAD_SESSIONS_ACTIVE._value.get() == active + 1
    assert UPLOAD_SESSIONS_STALLED._value.get() == stalled + 1
    with Session(get_catalog_engine()) as db:
        db.get(UploadSession, upload_id).expires_at = now() - timedelta(seconds=1)
        db.commit()
    update_upload_metrics()
    assert UPLOAD_SESSIONS_ACTIVE._value.get() == active
    assert UPLOAD_SESSIONS_STALLED._value.get() == stalled


def test_orphan_collection_keeps_recent_and_catalog_references(api, monkeypatch):
    client, manager, create, _, _ = api
    upload_id = uuid.UUID(create(4).json()["uploadId"])
    with Session(get_catalog_engine()) as db:
        retained_id = db.get(UploadSession, upload_id).file_id
    old_id, recent_id = uuid.uuid4(), uuid.uuid4()
    ids = [old_id, recent_id, retained_id]
    with get_storage_engine().begin() as connection:
        for file_id in ids:
            connection.execute(text(
                "INSERT INTO file_contents (file_id, content, created_at) VALUES (:id, :content, :created)"
            ), {
                "id": file_id, "content": b"bytes",
                "created": now() - timedelta(minutes=11) if file_id != recent_id else now(),
            })
    monkeypatch.setattr("app.jobs.orphans.BATCH_SIZE", 1)
    try:
        assert client.portal.call(delete_orphan_contents, manager) >= 1
        with get_storage_engine().connect() as connection:
            remaining = set(connection.execute(text(
                "SELECT file_id FROM file_contents WHERE file_id IN (:old, :recent, :retained)"
            ), {"old": old_id, "recent": recent_id, "retained": retained_id}).scalars())
        assert remaining == {recent_id, retained_id}
    finally:
        with get_storage_engine().begin() as connection:
            for file_id in ids:
                connection.execute(text("DELETE FROM file_contents WHERE file_id=:id"), {"id": file_id})
