#!/usr/bin/env python3
"""Step 6 checks over HTTPS: python3 scripts/smoke_files.py (running Compose stack)."""
from __future__ import annotations

import hashlib
import http.client
import json
import ssl
import uuid
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from smoke_auth import container_python


def main() -> None:
    config = container_python("""
import json
from app.core.settings import get_settings
s = get_settings()
print(json.dumps({
    "origin": str(s.app_origin).rstrip("/"),
    "cookie": s.session_cookie_name,
    "password": s.storage_secret("operator_password"),
}))
""")
    run_id = f"files-smoke-{uuid.uuid4().hex}"
    jar = CookieJar()
    opener = build_opener(
        HTTPCookieProcessor(jar), HTTPSHandler(context=ssl._create_unverified_context())
    )
    csrf = ""
    session_id = None

    def request(path, *, method="GET", body=None, headers=None, expected=200):
        supplied = {"X-Request-Id": run_id, **(headers or {})}
        if method != "GET":
            supplied.update({"Origin": config["origin"], "X-CSRF-Token": csrf})
        req = Request(config["origin"] + "/api/v1" + path, data=body, method=method, headers=supplied)
        try:
            response = opener.open(req, timeout=60)
        except HTTPError as exc:
            response = exc
        with response:
            assert response.status == expected, f"{method} {path}: expected {expected}, got {response.status}"
            return response.read()

    def get(path):
        return json.loads(request(path))

    def upload(category, metadata, content):
        boundary = f"filegrid-{uuid.uuid4().hex}"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n"
            "Content-Type: application/json\r\n\r\n".encode(),
            json.dumps({"category": category, **metadata}).encode(),
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{run_id}-{category}.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        return json.loads(request("/files", method="POST", body=iter(parts), expected=201, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(sum(map(len, parts))),
        }))

    try:
        request("/auth/login", method="POST", body=json.dumps({
            "username": "operator", "password": config["password"],
        }).encode(), headers={"Content-Type": "application/json"})
        cookies = {cookie.name: cookie.value for cookie in jar}
        csrf = cookies["filegrid_csrf"]
        session_id = cookies[config["cookie"]].split(".")[0]
        asset = get("/assets")["items"][0]
        case = get("/connection-cases")["items"][0]
        doc_type = get("/document-types")[0]
        samples = [
            ("OUTAGE_RECORD", {
                "assetId": asset["id"], "regionId": asset["regionId"],
                "startedAt": "2026-01-01T10:00:00Z", "severity": "HIGH",
            }, b'{"outage":"smoke"}\r\n'),
            ("CONNECTION_DOCUMENT", {
                "caseId": case["id"], "documentTypeId": doc_type["id"],
            }, b"private-document\x00" * (20 * 1024 * 1024 // 17) + b"x" * (20 * 1024 * 1024 % 17)),
            ("DRONE_VIDEO", {
                "assetId": asset["id"], "recordedAt": "2026-01-01T10:00:00Z",
            }, bytes(range(256)) * (12 * 1024 * 1024 // 256)),
        ]
        for category, metadata, original in samples:
            file = upload(category, metadata, original)
            file_id = file["id"]
            digest = hashlib.sha256(original).hexdigest()
            assert file["status"] == "READY" and file["sha256"] == digest
            assert file["sizeBytes"] == len(original)
            listing = get("/files?" + urlencode({
                "category": category, "regionId": file["regionId"], "status": "READY", "size": 100,
            }))
            assert file_id in [item["id"] for item in listing["items"]]
            assert hashlib.sha256(request(f"/files/{file_id}/download")).hexdigest() == digest
            verification = get(f"/files/{file_id}/verify")
            assert verification["valid"] and verification["actualSha256"] == digest
            if category == "CONNECTION_DOCUMENT":
                checklist = get(f"/connection-cases/{case['id']}/documents")
                assert file_id in [doc["fileId"] for doc in checklist["documents"]]
                assert doc_type["id"] not in [doc["id"] for doc in checklist["missingDocumentTypes"]]
            print(f"{category}: upload -> list -> download -> verify SHA-256 equal")
            mutation = container_python("""
import hashlib, io, json, sys, uuid
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.models.files import File
from app.storage.registry import create_storages
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    file = db.get(File, uuid.UUID(data["fileId"]))
    assert file.original_name.startswith(data["runId"])
    backend, locator, encrypted = file.storage_backend, file.storage_locator, file.encrypted
adapter = create_storages(get_settings())[backend].adapter
stored = bytearray(b"".join(adapter.get(locator)))
not_plaintext = (
    hashlib.sha256(stored).hexdigest() != data["sha256"]
    and bytes.fromhex(data["prefixHex"]) not in stored
)
stored[-1] ^= 1
adapter.put(locator, io.BytesIO(stored), len(stored))
print(json.dumps({"encrypted": encrypted, "notPlaintext": not_plaintext}))
""", {
                "fileId": file_id, "runId": run_id, "sha256": digest,
                "prefixHex": original[:128].hex(),
            })
            if category == "CONNECTION_DOCUMENT":
                assert mutation["encrypted"] and mutation["notPlaintext"]
                print("CONNECTION_DOCUMENT: S3 bytes are encrypted, NOT plaintext (20 MiB boundary accepted)")
            if len(original) <= 10 * 1024 * 1024:
                request(f"/files/{file_id}/download", expected=409)
            else:
                try:
                    request(f"/files/{file_id}/download")
                except http.client.IncompleteRead:
                    pass
                else:
                    raise AssertionError("Corrupt large download completed instead of aborting")
            assert get(f"/files/{file_id}")["status"] == "CORRUPT"
            assert get(f"/files/{file_id}/verify")["valid"] is False
            print(f"{category}: flipped stored byte -> download refused/aborted -> CORRUPT")
    finally:
        container_python("""
import json, sys, uuid
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.clients import ClientDocument
from app.models.files import File
from app.models.inspections import VideoInspection
from app.models.outages import Outage
from app.storage.registry import create_storages
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    files = db.execute(select(
        File.id, File.storage_backend, File.storage_locator
    ).where(File.original_name.startswith(data["runId"]))).all()
storages = create_storages(get_settings())
for file in files:
    storages[file.storage_backend].adapter.delete(file.storage_locator)
with Session(get_catalog_engine()) as db:
    ids = [file.id for file in files]
    for model in (ClientDocument, Outage, VideoInspection):
        db.execute(delete(model).where(model.file_id.in_(ids)))
    db.execute(delete(File).where(File.id.in_(ids)))
    db.execute(delete(AuditEvent).where(AuditEvent.request_id == data["runId"]))
    if data["sessionId"]:
        db.execute(delete(UserSession).where(UserSession.id == uuid.UUID(data["sessionId"])))
    db.commit()
print(json.dumps({"cleaned": len(files)}))
""", {"runId": run_id, "sessionId": session_id})


if __name__ == "__main__":
    main()
