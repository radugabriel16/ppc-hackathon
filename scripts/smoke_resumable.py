#!/usr/bin/env python3
"""Step 8 HTTPS check: python3 scripts/smoke_resumable.py (running Compose stack)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import threading
import time
import uuid
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from smoke_auth import container_python

SIZE = 200 * 1024 * 1024
BLOCK = 1024 * 1024


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
    run_id = f"resumable-smoke-{uuid.uuid4().hex}"
    session_id = None
    stop = threading.Event()
    samples: list[tuple[float, str]] = []
    sampling_errors: list[str] = []
    container_id = subprocess.check_output(
        ["docker", "compose", "ps", "-q", "api-files"], text=True
    ).strip()
    assert container_id, "api-files is not running"

    def sample_memory():
        while not stop.is_set():
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container_id],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode:
                sampling_errors.append(result.stderr.strip())
                return
            usage = result.stdout.strip()
            match = re.match(r"([\d.]+)\s*(B|KiB|MiB|GiB)", usage)
            if match is None:
                sampling_errors.append(f"Unrecognized docker stats output: {usage}")
                return
            samples.append((
                float(match[1]) * {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[match[2]],
                usage,
            ))
            stop.wait(0.25)

    monitor = threading.Thread(target=sample_memory)
    monitor.start()
    try:
        with TemporaryDirectory(prefix="filegrid-resume-") as directory, TemporaryFile() as original:
            cookie_path = Path(directory) / "cookies.txt"

            def connect():
                jar = MozillaCookieJar(str(cookie_path))
                if cookie_path.exists():
                    jar.load(ignore_discard=True, ignore_expires=True)
                opener = build_opener(
                    HTTPCookieProcessor(jar),
                    HTTPSHandler(context=ssl._create_unverified_context()),
                )
                return jar, opener

            jar, opener = connect()

            def response(path, *, method="GET", body=None, headers=None, expected=200):
                supplied = {"X-Request-Id": run_id, **(headers or {})}
                if method != "GET":
                    supplied.update({
                        "Origin": config["origin"],
                        "X-CSRF-Token": next((c.value for c in jar if c.name == "filegrid_csrf"), ""),
                    })
                req = Request(
                    config["origin"] + "/api/v1" + path, data=body, method=method, headers=supplied
                )
                try:
                    result = opener.open(req, timeout=120)
                except HTTPError as exc:
                    result = exc
                if result.status != expected:
                    with result:
                        raise AssertionError(f"{method} {path}: {result.status} {result.read(4096)!r}")
                return result

            def request(path, *, method="GET", data=None, expected=200):
                with response(path, method=method, expected=expected,
                              body=json.dumps(data).encode() if data is not None else None,
                              headers={"Content-Type": "application/json"}) as result:
                    body = result.read()
                    return json.loads(body) if body else None

            request("/auth/login", method="POST", data={
                "username": "operator", "password": config["password"],
            })
            session_id = next(c.value for c in jar if c.name == config["cookie"]).split(".")[0]
            asset = request("/assets")["items"][0]
            whole = hashlib.sha256()
            for _ in range(SIZE // BLOCK):
                chunk = os.urandom(BLOCK)
                original.write(chunk)
                whole.update(chunk)
            digest = whole.hexdigest()
            upload = request("/uploads", method="POST", expected=201, data={
                "category": "DRONE_VIDEO", "fileName": f"{run_id}.bin",
                "sizeBytes": SIZE, "sha256": digest, "metadata": {
                    "category": "DRONE_VIDEO", "assetId": asset["id"],
                    "regionId": asset["regionId"], "recordedAt": "2026-01-01T10:00:00Z",
                },
            })
            upload_id, chunk_size, total_parts = (
                upload["uploadId"], upload["chunkSize"], upload["totalParts"]
            )

            def send_part(number, expected=200):
                original.seek((number - 1) * chunk_size)
                content = original.read(chunk_size)
                with response(
                    f"/uploads/{upload_id}/parts/{number}", method="PUT", expected=expected,
                    body=content, headers={
                        "Content-Type": "application/octet-stream",
                        "X-Part-SHA256": hashlib.sha256(content).hexdigest(),
                    },
                ) as result:
                    return json.loads(result.read())

            for number in range(1, total_parts // 2 + 1):
                send_part(number)
            jar.save(ignore_discard=True, ignore_expires=True)
            # Discard the client and local part tracking; rebuild from persisted cookies + GET.
            jar, opener = connect()
            status = request(f"/uploads/{upload_id}")
            assert status["receivedParts"] == list(range(1, total_parts // 2 + 1))
            duplicate = status["receivedParts"][0]
            send_part(duplicate)
            missing = sorted(set(range(1, total_parts + 1)) - set(status["receivedParts"]))
            for number in missing:
                send_part(number)
            print(f"200 MiB: resumed after client restart; {len(missing)} missing parts + one duplicate")
            completed = request(
                f"/uploads/{upload_id}/complete", method="POST", data={"sha256": digest}, expected=202
            )
            assert completed["status"] == "VERIFYING"
            file_id = completed["fileId"]
            deadline = time.monotonic() + 120
            while True:
                file = request(f"/files/{file_id}")
                if file["status"] != "VERIFYING" or time.monotonic() >= deadline:
                    break
                time.sleep(0.5)
            assert file["status"] == "READY", file
            downloaded = hashlib.sha256()
            size = 0
            with response(f"/files/{file_id}/download") as result:
                while chunk := result.read(BLOCK):
                    downloaded.update(chunk)
                    size += len(chunk)
            assert size == SIZE and downloaded.hexdigest() == digest
            send_part(1, expected=409)
            print("VERIFYING -> READY; streamed download SHA-256 matches; completed-session part rejected")
    finally:
        stop.set()
        monitor.join(timeout=20)
        container_python("""
import json, sys, uuid
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.enums import StorageBackend
from app.models.files import File
from app.models.inspections import VideoInspection
from app.models.uploads import UploadSession
from app.storage.registry import create_storages
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    rows = db.execute(select(
        UploadSession.id, UploadSession.file_id, UploadSession.s3_upload_id
    ).where(UploadSession.file_name == data["runId"] + ".bin")).all()
adapter = create_storages(get_settings())[StorageBackend.s3].adapter
for row in rows:
    if row.s3_upload_id:
        adapter.abort_multipart(str(row.file_id), row.s3_upload_id)
    adapter.delete(str(row.file_id))
with Session(get_catalog_engine()) as db:
    ids = [row.file_id for row in rows]
    db.execute(delete(UploadSession).where(UploadSession.id.in_([row.id for row in rows])))
    db.execute(delete(VideoInspection).where(VideoInspection.file_id.in_(ids)))
    db.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(ids)))
    db.execute(delete(AuditEvent).where(AuditEvent.request_id == data["runId"]))
    db.execute(delete(File).where(File.id.in_(ids)))
    if data["sessionId"]:
        db.execute(delete(UserSession).where(UserSession.id == uuid.UUID(data["sessionId"])))
    db.commit()
print(json.dumps({"cleaned": len(rows)}))
""", {"runId": run_id, "sessionId": session_id})
    assert not sampling_errors, sampling_errors
    assert samples, "No docker stats samples collected"
    print(f"api-files peak sampled memory (docker stats --no-stream): {max(samples)[1]}")


if __name__ == "__main__":
    main()
