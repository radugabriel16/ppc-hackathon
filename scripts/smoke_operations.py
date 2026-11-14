#!/usr/bin/env python3
"""HTTPS issue/admin smoke + internal alert delivery against the running Compose stack."""
import json
import ssl
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from smoke_auth import container_python


def main():
    config = container_python("""
import json
from app.core.settings import get_settings
s = get_settings()
print(json.dumps({
    "origin": str(s.app_origin).rstrip("/"),
    "cookie": s.session_cookie_name,
    "passwords": {name: s.storage_secret(name + "_password") for name in ("operator", "manager")},
}))
""")
    run_id = f"operations-smoke-{uuid.uuid4().hex}"
    sessions = []
    cookies = {}

    def request(path, method="GET", body=None, expected=200):
        headers = {"X-Request-Id": run_id, "Content-Type": "application/json"}
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        if method != "GET":
            headers.update({
                "Origin": config["origin"], "X-CSRF-Token": cookies.get("filegrid_csrf", ""),
            })
        req = Request(
            config["origin"] + "/api/v1" + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            response = urlopen(req, context=ssl._create_unverified_context(), timeout=20)
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            allowed = (expected,) if isinstance(expected, int) else expected
            assert response.status in allowed, f"{method} {path}: {response.status} {content[:1024]!r}"
            for value in response.headers.get_all("Set-Cookie", []):
                parsed = SimpleCookie()
                parsed.load(value)
                cookies.update({key: morsel.value for key, morsel in parsed.items()})
            result = None
            if content:
                result = (
                    json.loads(content) if response.headers.get_content_type() == "application/json"
                    else content.decode()
                )
            return response.status, result

    def login(username):
        request("/auth/login", "POST", {
            "username": username, "password": config["passwords"][username],
        })
        sessions.append(cookies[config["cookie"]].split(".")[0])

    try:
        request("/alerts/recent", expected=401)
        request("/admin/scenario-runs", expected=401)
        # Test normalized and trailing-slash paths through the public gateway.
        for path in ("/alerts/webhook", "/alerts/webhook/", "/alerts/%77ebhook"):
            request(path, "POST", {}, expected=404)
        login("operator")
        _, assets = request("/assets?size=100")
        asset = next(row for row in assets["items"] if row["code"].startswith("MUN-"))
        _, issue = request("/map-issues", "POST", {
            "assetId": asset["id"], "severity": "HIGH",
            "description": run_id, "location": {"type": "Point", "coordinates": [26.1, 44.4]},
        }, expected=201)
        path = f"/map-issues/{issue['id']}/status"
        barrier = threading.Barrier(2)

        def claim(team):
            barrier.wait(timeout=10)
            return request(path, "PATCH", {
                "status": "IN_PROGRESS", "version": issue["version"], "assignedTeamLabel": team,
            }, expected=(200, 409))

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["smoke A", "smoke B"]))
        assert sorted(status for status, _ in results) == [200, 409]
        claimed = next(body for status, body in results if status == 200)
        request(path, "PATCH", {"status": "RESOLVED", "version": claimed["version"]}, expected=403)
        request("/admin/simulator/status", expected=403)
        print("PASS: public webhook blocked; concurrent claims 200/409; operator cannot resolve/admin")

        # Deliver over the internal network, without cookies, Origin or CSRF.
        alert = {
            "version": "4", "status": "firing", "receiver": "filegrid", "groupKey": run_id,
            "alerts": [{
                "status": "firing", "labels": {
                    "alertname": "SmokeAlert", "severity": "warning", "testRun": run_id,
                }, "annotations": {"summary": run_id}, "startsAt": "2026-11-14T10:00:00Z",
            }],
        }
        delivered = container_python("""
import json, sys, urllib.request
body = json.load(sys.stdin)
req = urllib.request.Request(
    "http://api-files:8000/api/v1/alerts/webhook",
    data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=10) as response:
    print(json.dumps(response.status))
""", alert)
        assert delivered == 204
        _, recent = request("/alerts/recent")
        assert any(row["message"] == run_id and row["severity"] == "warning" for row in recent)

        login("manager")
        _, resolved = request(path, "PATCH", {"status": "RESOLVED", "version": claimed["version"]})
        assert resolved["resolvedAt"] and resolved["version"] == claimed["version"] + 1
        for action in ("status", "start", "stop", "backfill"):
            _, unavailable = request(
                "/admin/simulator/" + action, "GET" if action == "status" else "POST",
                expected=503,
            )
            assert unavailable["code"] == "SIMULATOR_UNAVAILABLE"
            assert "not running" in unavailable["message"]

        scenario_id = container_python("""
import json, sys
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.models.jobs import ScenarioRun
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    row = ScenarioRun(
        kind="smoke", profile=data["runId"], started_at=datetime.now(timezone.utc),
        counters={"readings": 3},
    )
    db.add(row)
    db.commit()
    print(json.dumps(str(row.id)))
""", {"runId": run_id})
        _, scenarios = request("/admin/scenario-runs?size=100")
        assert any(row["id"] == scenario_id and row["counters"] == {"readings": 3}
                   for row in scenarios["items"])
        audit = container_python("""
import json, sys, uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.models.audit import AuditEvent
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    rows = db.scalars(select(AuditEvent).where(
        AuditEvent.entity_id == uuid.UUID(data["id"]),
    ).order_by(AuditEvent.occurred_at)).all()
    print(json.dumps([row.details["version"] for row in rows]))
""", {"id": issue["id"]})
        assert audit == [1, 2, 3]
        print("PASS: persisted alerts; manager resolve; four simulator 503s; scenario history; audit")
    finally:
        container_python("""
import json, sys, uuid
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.models.alerts import Alert
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.issues import MapIssue
from app.models.jobs import ScenarioRun
data = json.load(sys.stdin)
with Session(get_catalog_engine()) as db:
    db.execute(delete(AuditEvent).where(AuditEvent.request_id == data["runId"]))
    db.execute(delete(MapIssue).where(MapIssue.description.endswith(data["runId"])))
    db.execute(delete(Alert).where(Alert.payload["labels"]["testRun"].astext == data["runId"]))
    db.execute(delete(ScenarioRun).where(ScenarioRun.profile == data["runId"]))
    db.execute(delete(UserSession).where(UserSession.id.in_([uuid.UUID(x) for x in data["sessions"]])))
    db.commit()
print(json.dumps("cleaned"))
""", {"runId": run_id, "sessions": sessions})


if __name__ == "__main__":
    main()
