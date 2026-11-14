import hashlib
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_catalog_db, get_catalog_engine
from app.core.metrics import INTEGRITY_FAILURES_TOTAL
from app.core.settings import get_settings
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.clients import ClientDocument
from app.models.enums import FileCategory, FileStatus, StorageBackend
from app.models.files import File
from app.models.inspections import VideoInspection
from app.models.outages import Outage
from app.storage.base import StorageUnavailable

pytestmark = pytest.mark.integration
BASE = "/api/v1"


@pytest.fixture
def api(monkeypatch):
    settings = get_settings()
    run_id = f"step6-{uuid.uuid4().hex}"
    app = create_app()
    sessions = []
    session_id = None

    def tracked_db():
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            sessions.append(db)
            try:
                yield db
            finally:
                sessions.remove(db)

    app.dependency_overrides[get_catalog_db] = tracked_db
    with TestClient(
        app, base_url=str(settings.app_origin).rstrip("/"),
        headers={"Origin": str(settings.app_origin).rstrip("/"), "X-Request-Id": run_id},
        raise_server_exceptions=False,
    ) as client:
        manager = app.state.policy_manager
        for storage in manager.storages.values():
            original_put, original_get = storage.put, storage.get

            async def put(*args, original=original_put, **kwargs):
                assert all(not db.in_transaction() for db in sessions)
                return await original(*args, **kwargs)

            async def get(*args, original=original_get, **kwargs):
                assert all(not db.in_transaction() for db in sessions)
                async for chunk in original(*args, **kwargs):
                    yield chunk

            monkeypatch.setattr(storage, "put", put)
            monkeypatch.setattr(storage, "get", get)

        response = client.post(
            f"{BASE}/auth/login",
            json={
                "username": "operator",
                "password": (Path(settings.secrets_dir) / "operator_password").read_text().strip(),
            },
        )
        assert response.status_code == 200
        session_id = uuid.UUID(client.cookies[settings.session_cookie_name].split(".")[0])
        client.headers["X-CSRF-Token"] = client.cookies["filegrid_csrf"]
        asset = client.get(f"{BASE}/assets").json()["items"][0]
        case = client.get(f"{BASE}/connection-cases").json()["items"][0]
        doc_type = next(
            item for item in client.get(f"{BASE}/document-types").json()
            if item["code"] == "PROOF_OF_ADDRESS"
        )

        def metadata(category):
            if category == "CONNECTION_DOCUMENT":
                return {"category": category, "caseId": case["id"], "documentTypeId": doc_type["id"]}
            if category == "OUTAGE_RECORD":
                return {
                    "category": category, "assetId": asset["id"],
                    "startedAt": "2026-01-01T10:00:00Z", "severity": "HIGH",
                    "description": "Smoke outage",
                }
            return {
                "category": category, "assetId": asset["id"], "recordedAt": "2026-01-01T10:00:00Z",
            }

        def upload(category, content=b"original\x00bytes\r\n", *, meta=None):
            return client.post(
                f"{BASE}/files",
                files={
                    "file": (f"{run_id}-{uuid.uuid4().hex}.bin", content, "application/octet-stream"),
                    "metadata": (None, json.dumps(meta or metadata(category)), "application/json"),
                },
            )

        try:
            yield client, manager, run_id, upload, metadata
        finally:
            with Session(get_catalog_engine()) as db:
                files = db.scalars(select(File).where(File.original_name.startswith(run_id))).all()
                for file in files:
                    try:
                        client.portal.call(
                            manager.storages[file.storage_backend].delete,
                            file.category, file.storage_locator,
                        )
                    except StorageUnavailable:
                        # A failure test may deliberately leave the in-process breaker open.
                        manager.storages[file.storage_backend].adapter.delete(file.storage_locator)
                ids = [file.id for file in files]
                for model in (ClientDocument, Outage, VideoInspection):
                    db.execute(delete(model).where(model.file_id.in_(ids)))
                db.execute(delete(File).where(File.id.in_(ids)))
                db.execute(delete(AuditEvent).where(AuditEvent.request_id == run_id))
                db.execute(delete(UserSession).where(UserSession.id == session_id))
                db.commit()


@pytest.mark.parametrize(
    "category,size",
    [("OUTAGE_RECORD", 117), ("CONNECTION_DOCUMENT", 2 * 1024 * 1024 + 17),
     ("DRONE_VIDEO", 12 * 1024 * 1024)],
)
def test_upload_domain_list_download_and_verify(api, category, size):
    client, manager, run_id, upload, metadata = api
    content = (bytes(range(256)) * (size // 256 + 1))[:size]
    response = upload(category, content)
    assert response.status_code == 201, response.text
    file = response.json()
    assert file["status"] == "READY"
    assert file["sha256"] == hashlib.sha256(content).hexdigest()
    assert file["sizeBytes"] == size
    assert file["encrypted"] == (category == "CONNECTION_DOCUMENT")
    file_id = file["id"]
    assert client.get(f"{BASE}/files/{file_id}").json() == file
    listing = client.get(f"{BASE}/files", params={
        "category": category, "regionId": file["regionId"], "status": "READY", "size": 100000,
    }).json()
    assert listing["size"] == 100
    assert file_id in [item["id"] for item in listing["items"]]
    assert client.get(f"{BASE}/files", params={"page": 100000}).json()["items"] == []
    download = client.get(f"{BASE}/files/{file_id}/download")
    assert download.status_code == 200
    assert download.content == content
    verification = client.get(f"{BASE}/files/{file_id}/verify").json()
    assert verification["valid"]
    assert verification["actualSha256"] == file["sha256"]
    assert verification["checkedAt"]
    with Session(get_catalog_engine()) as db:
        row = db.get(File, uuid.UUID(file_id))
        assert row.last_verified_at is not None
        model = {
            "OUTAGE_RECORD": Outage, "CONNECTION_DOCUMENT": ClientDocument,
            "DRONE_VIDEO": VideoInspection,
        }[category]
        assert db.scalar(select(model).where(model.file_id == row.id)) is not None
        if category == "CONNECTION_DOCUMENT":
            stored = b"".join(manager.storages[StorageBackend.s3].adapter.get(row.storage_locator))
            assert stored != content and content[:128] not in stored
            assert row.encryption_key_id == client.app.state.document_key.id
            assert db.scalar(select(AuditEvent).where(
                AuditEvent.request_id == run_id, AuditEvent.action == "DOCUMENT_DOWNLOAD_REQUESTED",
            )) is not None
    if category == "CONNECTION_DOCUMENT":
        meta = metadata(category)
        checklist = client.get(f"{BASE}/connection-cases/{meta['caseId']}/documents").json()
        assert file_id in [doc["fileId"] for doc in checklist["documents"]]
        assert meta["documentTypeId"] not in [doc["id"] for doc in checklist["missingDocumentTypes"]]


@pytest.mark.parametrize("category", ["OUTAGE_RECORD", "CONNECTION_DOCUMENT"])
def test_corrupt_storage_refuses_download_and_verify_rereads(api, category):
    client, manager, run_id, upload, _ = api
    file = upload(category).json()
    file_id = file["id"]
    with Session(get_catalog_engine()) as db:
        row = db.get(File, uuid.UUID(file_id))
        adapter = manager.storages[row.storage_backend].adapter
        stored = bytearray(b"".join(adapter.get(row.storage_locator)))
        stored[-1] ^= 1
        adapter.put(row.storage_locator, io.BytesIO(stored), len(stored))
    metric = INTEGRITY_FAILURES_TOTAL.labels(category=category, storage=file["storageBackend"])
    before = metric._value.get()
    assert client.get(f"{BASE}/files/{file_id}/download").status_code == 409
    assert client.get(f"{BASE}/files/{file_id}").json()["status"] == "CORRUPT"
    assert metric._value.get() == before + 1
    assert client.get(f"{BASE}/files/{file_id}/verify").json()["valid"] is False
    with Session(get_catalog_engine()) as db:
        assert db.scalar(select(AuditEvent).where(
            AuditEvent.request_id == run_id, AuditEvent.action == "FILE_INTEGRITY_FAILED",
        )) is not None
    # Even a previously CORRUPT file must be re-read, not answered from status.
    if not file["encrypted"]:
        original = b"original\x00bytes\r\n"
        adapter.put(row.storage_locator, io.BytesIO(original), len(original))
        assert client.get(f"{BASE}/files/{file_id}/verify").json()["valid"] is True


def test_encrypted_plaintext_policy_boundary_and_video_chunk_limit(api):
    client, manager, _, upload, _ = api
    manager.config.categories[FileCategory.CONNECTION_DOCUMENT].max_size_bytes = 128
    assert upload("CONNECTION_DOCUMENT", b"x" * 128).status_code == 201
    assert upload("CONNECTION_DOCUMENT", b"x" * 129).status_code == 413
    manager.config.categories[FileCategory.DRONE_VIDEO].chunk_size_bytes = 128
    assert upload("DRONE_VIDEO", b"x" * 129).status_code == 413


def test_validation_auth_and_csrf(api):
    client, _, _, upload, metadata = api
    meta = metadata("OUTAGE_RECORD")
    meta["regionId"] = str(uuid.uuid4())
    assert upload("OUTAGE_RECORD", meta=meta).status_code == 422
    meta = metadata("CONNECTION_DOCUMENT")
    meta["caseId"] = str(uuid.uuid4())
    assert upload("CONNECTION_DOCUMENT", meta=meta).status_code == 404
    meta = metadata("OUTAGE_RECORD")
    meta["startedAt"] = "2026-01-01T00:00:00"
    assert upload("OUTAGE_RECORD", meta=meta).status_code == 422
    assert upload("METER_READING", meta={"category": "METER_READING"}).status_code == 422
    token = client.headers.pop("X-CSRF-Token")
    assert upload("OUTAGE_RECORD").status_code == 403
    client.headers["X-CSRF-Token"] = token
    client.cookies.clear()
    for path in ("/files", "/regions", "/assets", "/meters", "/clients",
                 "/connection-cases", "/document-types", "/map/features?layer=ASSETS"):
        assert client.get(BASE + path).status_code == 401
        assert client.get(BASE + path, headers={"Authorization": "Bearer invalid"}).status_code == 401


@pytest.mark.parametrize("failure", ["fallback", "unavailable", "domain", "bulkhead"])
def test_storage_fallback_and_failure_lifecycle(api, monkeypatch, failure):
    client, manager, run_id, upload, _ = api

    async def unavailable(*args, **kwargs):
        raise StorageUnavailable("injected failure")

    def unavailable_adapter(*args):
        raise OSError("injected FTP failure")

    borrower = object()
    limiter = manager.bulkheads[FileCategory.OUTAGE_RECORD]
    if failure == "fallback":
        monkeypatch.setattr(manager.storages[StorageBackend.ftp].adapter, "put", unavailable_adapter)
    elif failure == "unavailable":
        for storage in manager.storages.values():
            monkeypatch.setattr(storage, "put", unavailable)
    elif failure == "domain":
        def fail_link(*args):
            raise SQLAlchemyError("injected domain failure")
        monkeypatch.setattr("app.files.service.link_outage", fail_link)
    else:
        limiter.total_tokens = 1
        client.portal.call(limiter.acquire_on_behalf_of_nowait, borrower)
    try:
        response = upload("OUTAGE_RECORD")
    finally:
        if failure == "bulkhead":
            client.portal.call(limiter.release_on_behalf_of, borrower)
    if failure == "fallback":
        assert response.status_code == 201
        assert response.json()["fallbackUsed"]
        assert response.json()["storageBackend"] == "s3"
        assert client.get(f"{BASE}/files/{response.json()['id']}/download").content == b"original\x00bytes\r\n"
    else:
        assert response.status_code == (500 if failure == "domain" else 503)
        if failure != "domain":
            assert response.headers["Retry-After"] == "1"
        with Session(get_catalog_engine()) as db:
            file = db.scalar(select(File).where(File.original_name.startswith(run_id)))
            assert file.status == FileStatus.FAILED
            assert db.scalar(select(Outage).where(Outage.file_id == file.id)) is None


def test_ui_reads_region_filters_pagination_and_pii_free_map(api):
    client, _, _, upload, _ = api
    regions = client.get(f"{BASE}/regions").json()
    region_id = regions["items"][0]["id"]
    assert regions["items"][0]["center"]["type"] == "Point"
    assert len(regions["items"][0]["center"]["coordinates"]) == 2
    for path in ("/assets", "/meters", "/clients", "/connection-cases"):
        payload = client.get(BASE + path, params={"regionId": region_id, "size": 1}).json()
        assert len(payload["items"]) <= 1
        assert payload["totalElements"] > 0
        if path in ("/assets", "/clients"):
            assert all(item["regionId"] == region_id for item in payload["items"])
    assert client.get(f"{BASE}/clients", params={"regionId": str(uuid.uuid4())}).json()["items"] == []
    for path in ("/clients", "/connection-cases", "/assets", "/meters", "/regions", "/files"):
        assert client.get(BASE + path, params={"page": -1}).status_code == 422
        assert client.get(BASE + path, params={"size": 0}).status_code == 422
    upload("OUTAGE_RECORD")
    allowed = {
        "ASSETS": {"id", "kind", "assetType", "code", "name"},
        "ISSUES": {"id", "kind", "assetId", "severity", "status", "version"},
        "OUTAGES": {"id", "kind", "assetId", "severity", "startedAt", "endedAt"},
    }
    for layer in allowed:
        features = client.get(f"{BASE}/map/features", params={"layer": layer}).json()
        assert features["type"] == "FeatureCollection" and features["features"]
        assert all(set(feature["properties"]) <= allowed[layer] for feature in features["features"])
        assert client.get(f"{BASE}/map/features", params={
            "layer": layer, "regionId": str(uuid.uuid4()),
        }).json()["features"] == []
