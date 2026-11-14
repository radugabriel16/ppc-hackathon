#!/usr/bin/env python3
"""Step 7 HTTPS checks, including a temporary stop/restart of Compose storage-db."""
from __future__ import annotations

import json
import ssl
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen

from smoke_auth import container_python


def compose(*args):
    result = subprocess.run(
        ["docker", "compose", *args], text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"Compose {' '.join(args)} failed:\n{result.stderr[-4000:]}")


def main() -> None:
    config = container_python("""
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.models.metering import Meter
s = get_settings()
with Session(get_catalog_engine()) as db:
    meter = db.scalars(select(Meter).order_by(Meter.external_code)).first()
    print(json.dumps({
        "origin": str(s.app_origin).rstrip("/"),
        "cookie": s.session_cookie_name,
        "password": s.storage_secret("operator_password"),
        "token": s.storage_secret("simulator_token"),
        "meterId": str(meter.id), "meterCode": meter.external_code,
    }))
""")
    run_id = f"meter-smoke-{uuid.uuid4().hex}"
    base = config["origin"] + "/api/v1"
    context = ssl._create_unverified_context()
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar), HTTPSHandler(context=context))
    session_id = None
    restore_storage = False
    keys = []
    start = datetime.now(timezone.utc).replace(microsecond=uuid.uuid4().int % 1_000_000)

    def payload(offset):
        interval = start + timedelta(minutes=offset)
        iso = interval.isoformat().replace("+00:00", "Z")
        key = f"{config['meterCode']}:{iso}"
        keys.append(key)
        return {
            "meterExternalCode": config["meterCode"], "readingKey": key, "seq": offset,
            "intervalStart": iso, "intervalEnd": (interval + timedelta(minutes=15)).isoformat(),
            "energyKwh": 3.42,
        }

    def ingest(body, expected=None, *, token=None):
        request = Request(
            base + "/meter-readings/ingest", method="POST",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json", "X-Request-Id": run_id,
                "Authorization": f"Bearer {config['token'] if token is None else token}",
            },
        )
        try:
            response = urlopen(request, context=context, timeout=45)
        except HTTPError as exc:
            response = exc
        with response:
            status, headers = response.status, response.headers
            result = json.load(response)
        if expected is not None:
            assert status == expected, f"Ingest expected {expected}, got {status}: {result.get('code')}"
        return status, headers, result

    def catalog_check(body, expected):
        result = container_python("""
import json, sys
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.models.metering import MeterReading
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    count = db.scalar(select(func.count()).select_from(MeterReading).where(
        MeterReading.reading_key == data["key"]
    ))
print(json.dumps({"count": count}))
""", {"key": body["readingKey"]})
        assert result["count"] == expected, result

    try:
        first = payload(0)
        ingest(first, 401, token="invalid")
        created = ingest(first, 201)[2]
        assert ingest(first, 200)[2] == created
        ingest({**first, "energyKwh": 99}, 409)
        print("PASS new -> 201, identical -> 200, changed -> 409")

        concurrent = payload(1)
        with ThreadPoolExecutor(max_workers=20) as pool:
            statuses = list(pool.map(lambda _: ingest(concurrent)[0], range(20)))
        assert statuses.count(201) == 1 and statuses.count(200) == 19, statuses
        catalog_check(concurrent, 1)
        print("PASS 20 concurrent identical deliveries -> one catalog row (1 x 201, 19 x 200)")

        login = Request(
            base + "/auth/login", method="POST",
            data=json.dumps({"username": "operator", "password": config["password"]}).encode(),
            headers={"Content-Type": "application/json", "Origin": config["origin"], "X-Request-Id": run_id},
        )
        with opener.open(login, timeout=15) as response:
            assert response.status == 200
        session_id = next(cookie.value.split(".")[0] for cookie in jar if cookie.name == config["cookie"])
        query = urlencode({
            "meterId": config["meterId"], "from": first["intervalEnd"],
            "to": concurrent["intervalEnd"], "size": 1000,
        })
        with opener.open(base + "/meter-readings?" + query, timeout=15) as response:
            listing = json.load(response)
        assert listing["size"] == 100
        assert {first["readingKey"], concurrent["readingKey"]} <= {
            row["readingKey"] for row in listing["items"]
        }
        print("PASS session authenticated GET /meter-readings through nginx, filters and size cap")

        restore_storage = True
        compose("stop", "-t", "5", "storage-db")
        unavailable = payload(2)
        _, headers, _ = ingest(unavailable, 503)
        assert int(headers["Retry-After"]) >= 1
        catalog_check(unavailable, 0)
        print("PASS storage-db stopped -> 503 + Retry-After, no catalog row")
        compose("start", "--wait", "--wait-timeout", "60", "storage-db")
        restore_storage = False
        deadline = time.monotonic() + 40
        while True:
            status, headers, _ = ingest(unavailable)
            if status == 201:
                break
            assert status == 503 and time.monotonic() < deadline, status
            time.sleep(int(headers["Retry-After"]))
        catalog_check(unavailable, 1)
        print("PASS storage-db restarted -> 201 again")
    finally:
        if restore_storage:
            compose("start", "--wait", "--wait-timeout", "60", "storage-db")
        container_python("""
import json, sys, uuid
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine, get_storage_engine
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.files import File
from app.models.metering import MeterReading
from app.storage.db import DbStorage
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    ids = list(db.scalars(select(MeterReading.file_id).where(
        MeterReading.reading_key.in_(data["keys"])
    )))
    db.execute(delete(MeterReading).where(MeterReading.file_id.in_(ids)))
    db.execute(delete(File).where(File.id.in_(ids)))
    db.execute(delete(AuditEvent).where(AuditEvent.request_id == data["runId"]))
    if data["sessionId"]:
        db.execute(delete(UserSession).where(UserSession.id == uuid.UUID(data["sessionId"])))
    db.commit()
for file_id in ids:
    DbStorage(get_storage_engine()).delete(str(file_id))
print(json.dumps({"cleaned": len(ids)}))
""", {"keys": keys, "runId": run_id, "sessionId": session_id})


if __name__ == "__main__":
    main()
