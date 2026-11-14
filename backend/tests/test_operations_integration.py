import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.admin import router as admin_module
from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.main import create_app
from app.models.alerts import Alert
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.enums import IssueStatus
from app.models.issues import MapIssue
from app.models.jobs import ScenarioRun

pytestmark = pytest.mark.integration
BASE = "/api/v1"


@pytest.fixture
def api():
    settings = get_settings()
    run_id = f"operations-{uuid.uuid4().hex}"
    session_ids = []
    app = create_app()
    try:
        with TestClient(
            app, base_url=str(settings.app_origin).rstrip("/"),
            headers={"Origin": str(settings.app_origin).rstrip("/"), "X-Request-Id": run_id},
            raise_server_exceptions=False,
        ) as client:
            def login(username="operator"):
                result = client.post(BASE + "/auth/login", json={
                    "username": username,
                    "password": (Path(settings.secrets_dir) / f"{username}_password").read_text().strip(),
                })
                assert result.status_code == 200, result.text
                session_ids.append(uuid.UUID(client.cookies[settings.session_cookie_name].split(".")[0]))
                client.headers["X-CSRF-Token"] = client.cookies["filegrid_csrf"]

            def create(**changes):
                assets = client.get(BASE + "/assets?size=100").json()["items"]
                asset = next(row for row in assets if row["code"].startswith("MUN-"))
                return client.post(BASE + "/map-issues", json={
                    "assetId": asset["id"], "location": {
                        "type": "Point", "coordinates": [26.1, 44.4],
                    }, "severity": "HIGH", "description": run_id, **changes,
                })

            yield client, login, create, run_id
    finally:
        with Session(get_catalog_engine()) as db:
            db.execute(delete(AuditEvent).where(AuditEvent.request_id == run_id))
            db.execute(delete(MapIssue).where(MapIssue.description.endswith(run_id)))
            db.execute(delete(Alert).where(Alert.payload["labels"]["testRun"].astext == run_id))
            db.execute(delete(ScenarioRun).where(ScenarioRun.profile == run_id))
            db.execute(delete(UserSession).where(UserSession.id.in_(session_ids)))
            db.commit()


def test_issue_claim_race_permissions_and_audit(api):
    client, login, create, run_id = api
    login()
    assert create(location={"type": "Point", "coordinates": [181, 44]}).status_code == 422
    assert create(assetId=str(uuid.uuid4())).status_code == 422
    assert create(videoInspectionId=str(uuid.uuid4())).status_code == 422
    assert create(videoOffsetSeconds=1).status_code == 422
    response = create()
    assert response.status_code == 201, response.text
    issue = response.json()
    assert issue["version"] == 1 and issue["status"] == "OPEN"
    assert issue["location"] == {"type": "Point", "coordinates": [26.1, 44.4]}
    path = f"{BASE}/map-issues/{issue['id']}/status"
    barrier = threading.Barrier(2)

    def claim(team):
        barrier.wait(timeout=10)
        return client.patch(path, json={
            "status": "IN_PROGRESS", "assignedTeamLabel": team, "version": 1,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(claim, ["Team A", "Team B"]))
    assert sorted(result.status_code for result in responses) == [200, 409]
    claimed = next(result.json() for result in responses if result.status_code == 200)
    assert claimed["version"] == 2
    features = client.get(BASE + "/map/features?layer=ISSUES").json()["features"]
    mapped = next(row["properties"] for row in features if row["properties"]["id"] == issue["id"])
    assert mapped["version"] == claimed["version"]
    assert "description" not in mapped
    assert client.patch(path, json={"status": "RESOLVED", "version": 2}).status_code == 403
    assert client.patch(path, json={"status": "OPEN", "version": 2},
                        headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.patch(
        f"{BASE}/map-issues/{uuid.uuid4()}/status",
        json={"status": "OPEN", "version": 1},
    ).status_code == 404
    login("manager")
    resolved = client.patch(path, json={"status": "RESOLVED", "version": 2})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolvedAt"] is not None
    assert resolved.json()["assignedTeamLabel"] == claimed["assignedTeamLabel"]
    reopened = client.patch(path, json={
        "status": "OPEN", "version": 3, "assignedTeamLabel": None,
    })
    assert reopened.status_code == 200
    assert reopened.json()["resolvedAt"] is None
    assert reopened.json()["assignedTeamLabel"] is None
    with Session(get_catalog_engine()) as db:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == uuid.UUID(issue["id"]),
        ).order_by(AuditEvent.occurred_at)).all()
        assert [row.details["version"] for row in events] == [1, 2, 3, 4]
        assert all(row.actor_id and row.request_id == run_id for row in events)


@pytest.mark.parametrize("operation", ["create", "update"])
def test_audit_failure_rolls_back_issue_mutation(api, operation):
    client, login, create, run_id = api
    login()
    issue = create().json() if operation == "update" else None

    def reject_audit(session, *_):
        if any(isinstance(row, AuditEvent) and row.entity_type == "map_issue"
               for row in session.new):
            raise RuntimeError("Injected audit write failure")

    event.listen(Session, "before_flush", reject_audit)
    try:
        if operation == "create":
            response = create()
        else:
            response = client.patch(f"{BASE}/map-issues/{issue['id']}/status", json={
                "status": "IN_PROGRESS", "version": 1,
            })
        assert response.status_code == 500, response.text
    finally:
        event.remove(Session, "before_flush", reject_audit)
    with Session(get_catalog_engine()) as db:
        rows = db.scalars(select(MapIssue).where(MapIssue.description.endswith(run_id))).all()
        if operation == "create":
            assert rows == []
        else:
            assert len(rows) == 1
            assert rows[0].version == 1 and rows[0].status == IssueStatus.OPEN
        assert len(db.scalars(select(AuditEvent).where(
            AuditEvent.request_id == run_id, AuditEvent.entity_type == "map_issue",
        )).all()) == (1 if operation == "update" else 0)


def webhook(run_id):
    return {
        "version": "4", "status": "firing", "receiver": "filegrid", "groupKey": "{}:test",
        "groupLabels": {}, "commonLabels": {}, "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093", "truncatedAlerts": 0,
        "alerts": [{
            "status": status, "labels": {
                "alertname": "StorageDown", "severity": "critical", "testRun": run_id,
            }, "annotations": {"summary": f"{run_id}-{status}"},
            "startsAt": "2026-11-14T10:00:00Z", "endsAt": "2026-11-14T11:00:00Z",
            "generatorURL": "http://prometheus:9090/graph", "fingerprint": status,
        } for status in ("firing", "resolved")],
    }


def test_internal_alertmanager_delivery_validation_and_authenticated_history(api):
    client, login, _, run_id = api
    assert client.get(BASE + "/alerts/recent").status_code == 401
    body = webhook(run_id)
    with TestClient(create_app()) as internal:
        result = internal.post(BASE + "/alerts/webhook", json=body)
        assert result.status_code == 204, result.text
        assert result.content == b""
        body["alerts"][1]["startsAt"] = "invalid"
        assert internal.post(BASE + "/alerts/webhook", json=body).status_code == 422
    login()
    with Session(get_catalog_engine()) as db:
        stored = db.scalars(select(Alert).where(
            Alert.payload["labels"]["testRun"].astext == run_id,
        )).all()
        assert len(stored) == 2
        assert {row.payload["status"] for row in stored} == {"firing", "resolved"}
        assert all(row.payload["generatorURL"] for row in stored)
        expected = {str(row.id) for row in stored}
    recent = client.get(BASE + "/alerts/recent").json()
    assert expected <= {row["id"] for row in recent}
    assert all(row["severity"] == "critical" for row in recent if row["id"] in expected)


def test_recent_alerts_are_capped_and_sorted_by_receipt(api):
    client, login, _, run_id = api
    login()
    now = datetime.now(timezone.utc)
    with Session(get_catalog_engine()) as db:
        for index in range(101):
            db.add(Alert(
                severity="warning", message=f"{run_id}-{index}", occurred_at=now,
                received_at=now + timedelta(microseconds=index),
                payload={"labels": {"testRun": run_id}},
            ))
        db.commit()
    recent = client.get(BASE + "/alerts/recent").json()
    assert len(recent) == 100
    assert [row["message"] for row in recent] == [
        f"{run_id}-{index}" for index in range(100, 0, -1)
    ]


@pytest.fixture
def upstream(monkeypatch):
    requests = []
    reply = {"status": 200, "body": {"running": True, "profile": "demo", "readingsPerSecond": 2}}

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size)) if size else None
            requests.append((self.command, self.path, body, self.headers.get("Cookie")))
            self.send_response(reply["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            content = reply["body"]
            self.wfile.write(content if isinstance(content, bytes) else json.dumps(content).encode())

        do_GET = handle_request
        do_POST = handle_request

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    def connection(host, port, timeout):
        assert (host, port, timeout) == ("simulator", 8080, 5)
        return HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)

    monkeypatch.setattr(admin_module, "HTTPConnection", connection)
    try:
        yield requests, reply
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


def test_simulator_proxy_roles_csrf_methods_payloads_and_upstream_errors(api, upstream):
    client, login, _, _ = api
    requests, reply = upstream
    assert client.get(BASE + "/admin/simulator/status").status_code == 401
    login()
    assert client.get(BASE + "/admin/scenario-runs").status_code == 403
    for action in ("status", "start", "stop", "backfill"):
        method = client.get if action == "status" else client.post
        assert method(BASE + "/admin/simulator/" + action).status_code == 403
    assert requests == []
    login("manager")
    status = client.get(BASE + "/admin/simulator/status")
    assert status.status_code == 200 and status.json() == reply["body"]
    assert client.post(BASE + "/admin/simulator/stop",
                       headers={"X-CSRF-Token": ""}).status_code == 403
    reply["status"] = 202
    for action, body in (
        ("start", {"profile": "demo", "readingsPerSecond": 2}),
        ("stop", None),
        ("backfill", {"profile": "demo", "from": "2026-11-01T00:00:00Z",
                      "to": "2026-11-02T00:00:00Z"}),
    ):
        response = client.post(BASE + "/admin/simulator/" + action, json=body)
        assert response.status_code == 202
        assert requests[-1] == ("POST", "/" + action, body, None)
    assert requests[0] == ("GET", "/status", None, None)
    reply.update(status=409, body={"code": "ALREADY_RUNNING", "message": "Already running"})
    assert client.post(BASE + "/admin/simulator/start").json() == reply["body"]
    assert client.post(BASE + "/admin/simulator/start").status_code == 409
    reply.update(status=200, body=b"not JSON")
    assert client.get(BASE + "/admin/simulator/status").status_code == 502


@pytest.mark.parametrize("action", ["status", "start", "stop", "backfill"])
def test_absent_simulator_returns_clear_503(api, monkeypatch, action):
    client, login, _, _ = api
    login("manager")

    class Unavailable:
        def request(self, *args, **kwargs):
            raise ConnectionRefusedError("simulator is stopped")

        def close(self):
            pass

    monkeypatch.setattr(admin_module, "HTTPConnection", lambda *args, **kwargs: Unavailable())
    method = client.get if action == "status" else client.post
    result = method(BASE + "/admin/simulator/" + action)
    assert result.status_code == 503
    assert result.json()["code"] == "SIMULATOR_UNAVAILABLE"
    assert "not running" in result.json()["message"]
    assert result.headers["Retry-After"] == "5"


def test_scenario_runs_reads_database_and_caps_pagination(api):
    client, login, _, run_id = api
    assert client.get(BASE + "/admin/scenario-runs").status_code == 401
    login("manager")
    now = datetime.now(timezone.utc)
    with Session(get_catalog_engine()) as db:
        first = ScenarioRun(
            kind="backfill", profile=run_id, started_at=now - timedelta(seconds=1),
            ended_at=now, counters={"readings": 20},
        )
        second = ScenarioRun(
            kind="live", profile=run_id, started_at=now, ended_at=None, counters=None,
        )
        db.add_all([first, second])
        db.commit()
        ids = [str(second.id), str(first.id)]
    page = client.get(BASE + "/admin/scenario-runs?size=1").json()
    assert page["items"][0]["id"] == ids[0] and page["size"] == 1
    assert client.get(BASE + "/admin/scenario-runs?page=1&size=1").json()["items"][0]["id"] == ids[1]
    rows = client.get(BASE + "/admin/scenario-runs?size=1000").json()
    assert rows["size"] == 100 and rows["totalElements"] >= 2
    assert next(row for row in rows["items"] if row["id"] == ids[1])["counters"] == {"readings": 20}
    assert client.get(BASE + "/admin/scenario-runs?size=0").status_code == 422
