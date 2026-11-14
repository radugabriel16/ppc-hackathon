#!/usr/bin/env python3
"""Step 4 integration checks: python3 scripts/smoke_auth.py (running Compose stack)."""
from __future__ import annotations

import itertools
import json
import subprocess
import tempfile
import uuid
from email.parser import Parser
from http.cookies import SimpleCookie
from pathlib import Path


def container_python(source: str, data: dict | None = None):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api-files", "python", "-c", source],
        input=json.dumps(data or {}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    config = container_python(
        """
import json
from pathlib import Path
from app.core.settings import get_settings
s = get_settings()
print(json.dumps({
    "origin": str(s.app_origin).rstrip("/"),
    "session_cookie": s.session_cookie_name,
    "passwords": {
        name: (Path(s.secrets_dir) / f"{name}_password").read_text().strip()
        for name in ("operator", "manager")
    },
}))
"""
    )
    origin = config["origin"]
    session_cookie = config["session_cookie"]
    run_id = f"auth-smoke-{uuid.uuid4().hex}"
    sequence = itertools.count()
    session_ids: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="filegrid-auth-") as directory:
        root = Path(directory)

        class Client:
            def __init__(self, name: str):
                self.jar = root / f"{name}.cookies"

            def cookies(self) -> dict[str, str]:
                cookies = {}
                for line in self.jar.read_text().splitlines() if self.jar.exists() else []:
                    if line.startswith("#") and not line.startswith("#HttpOnly_"):
                        continue
                    fields = line.split("\t")
                    if len(fields) == 7:
                        cookies[fields[5]] = fields[6]
                return cookies

            def request(
                self, method: str, path: str, expected: int, *, body=None, headers=None
            ):
                request_id = f"{run_id}-{next(sequence)}"
                supplied_headers = {"X-Request-Id": request_id, **(headers or {})}
                if method != "GET":
                    supplied_headers.setdefault("Origin", origin)
                options = {
                    "url": f"{origin}{path}",
                    "request": method,
                    "cookie": str(self.jar),
                    "cookie-jar": str(self.jar),
                    "output": str(root / "body"),
                    "dump-header": str(root / "headers"),
                    "write-out": "%{http_code}",
                    "max-time": "15",
                }
                lines = ["silent", "show-error", "insecure"]
                lines += [f"{key} = {json.dumps(value)}" for key, value in options.items()]
                for key, value in supplied_headers.items():
                    lines.append(f"header = {json.dumps(f'{key}: {value}')}")
                if body is not None:
                    lines.append('header = "Content-Type: application/json"')
                    lines.append(f"data-binary = {json.dumps(json.dumps(body))}")
                # Credentials and tokens go through stdin, never process arguments.
                result = subprocess.run(
                    ["curl", "--config", "-"],
                    input="\n".join(lines),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                status = int(result.stdout)
                assert status == expected, f"{method} {path}: expected {expected}, got {status}"
                raw_headers = (root / "headers").read_text()
                response_headers = Parser().parsestr(raw_headers.split("\n", 1)[1])
                assert response_headers["X-Request-Id"] == request_id
                raw_body = (root / "body").read_text()
                payload = json.loads(raw_body) if raw_body else None
                if status >= 400:
                    assert payload["requestId"] == request_id
                    assert {"code", "message", "fieldErrors", "requestId"} <= payload.keys()
                if path == "/api/v1/auth/login" and status == 200:
                    session_ids.add(self.cookies()[session_cookie].split(".")[0])
                return payload, response_headers

            def login(self, username: str):
                return self.request(
                    "POST",
                    "/api/v1/auth/login",
                    200,
                    body={"username": username, "password": config["passwords"][username]},
                )

        operator, manager, anonymous = (Client(name) for name in ("operator", "manager", "anon"))
        try:
            anonymous.request("GET", "/health/ready", 200)
            anonymous.request("GET", "/api/v1/auth/me", 401)
            anonymous.request("GET", "/api/v1/admin/policies", 401)
            anonymous.request(
                "GET", "/api/v1/auth/me", 401, headers={"Authorization": "Bearer invalid"}
            )
            for bad_origin in ("", "https://untrusted.invalid"):
                anonymous.request(
                    "POST",
                    "/api/v1/auth/login",
                    403,
                    headers={"Origin": bad_origin},
                    body={"username": "operator", "password": "invalid"},
                )
            for username in ("operator", "unknown-user"):
                payload, _ = anonymous.request(
                    "POST",
                    "/api/v1/auth/login",
                    401,
                    body={"username": username, "password": "invalid"},
                )
                assert payload["code"] == "INVALID_CREDENTIALS"
            print("PASS anonymous access, Origin enforcement and invalid credentials")

            identity, headers = operator.login("operator")
            assert identity["username"] == "operator" and identity["role"] == "OPERATOR"
            assert set(identity) == {"id", "username", "role"}
            assert headers["Cache-Control"] == "no-store"
            cookies = SimpleCookie()
            for header in headers.get_all("Set-Cookie", []):
                cookies.load(header)
            assert cookies[session_cookie]["secure"] and cookies[session_cookie]["httponly"]
            assert cookies[session_cookie]["samesite"].lower() == "lax"
            assert cookies["filegrid_csrf"]["secure"] and not cookies["filegrid_csrf"]["httponly"]
            assert cookies["filegrid_csrf"]["samesite"].lower() == "lax"
            current, _ = operator.request("GET", "/api/v1/auth/me", 200)
            assert current == identity
            operator.request("GET", "/api/v1/admin/policies", 403)
            token = operator.cookies()["filegrid_csrf"]
            session = operator.cookies()[session_cookie]
            for extra in (
                {},
                {"X-CSRF-Token": "invalid"},
                {"X-CSRF-Token": token, "Origin": ""},
                {"X-CSRF-Token": token, "Origin": "https://untrusted.invalid"},
                {
                    "X-CSRF-Token": "forged",
                    "Cookie": f"{session_cookie}={session}; filegrid_csrf=forged",
                },
            ):
                operator.request("POST", "/api/v1/auth/logout", 403, headers=extra)
            operator.request("GET", "/api/v1/auth/me", 200)
            print("PASS cookie flags, login/me, operator role and session-bound CSRF")

            operator.request(
                "POST", "/api/v1/auth/logout", 204, headers={"X-CSRF-Token": token}
            )
            assert not operator.cookies()
            operator.request("GET", "/api/v1/auth/me", 401)
            anonymous.request(
                "GET", "/api/v1/auth/me", 401, headers={"Cookie": f"{session_cookie}={session}"}
            )
            operator.login("operator")
            old_session = operator.cookies()[session_cookie]
            old_token = operator.cookies()["filegrid_csrf"]
            operator.login("operator")
            session = operator.cookies()[session_cookie]
            assert session != old_session and operator.cookies()["filegrid_csrf"] != old_token
            anonymous.request(
                "GET",
                "/api/v1/auth/me",
                401,
                headers={"Cookie": f"{session_cookie}={old_session}"},
            )
            replacement = "0" if session[-1] != "0" else "1"
            anonymous.request(
                "GET",
                "/api/v1/auth/me",
                401,
                headers={"Cookie": f"{session_cookie}={session[:-1]}{replacement}"},
            )
            container_python(
                """
import json, sys, uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import update
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.models.auth import UserSession
with Session(get_catalog_engine()) as db:
    db.execute(update(UserSession).where(
        UserSession.id == uuid.UUID(json.load(sys.stdin)["id"])
    ).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db.commit()
print("null")
""",
                {"id": session.split(".")[0]},
            )
            operator.request("GET", "/api/v1/auth/me", 401)
            print("PASS logout revocation, session rotation, cookie tampering and expiry")

            identity, _ = manager.login("manager")
            assert identity["role"] == "MANAGER"
            policies, _ = manager.request("GET", "/api/v1/admin/policies", 200)
            assert len(policies["categories"]) == 4
            manager.request(
                "POST",
                "/api/v1/auth/logout",
                204,
                headers={"X-CSRF-Token": manager.cookies()["filegrid_csrf"]},
            )
            manager.request("GET", "/api/v1/auth/me", 401)
            print("PASS manager-only endpoint and CSRF-authorized POST")

            for attempt in range(5):
                payload, headers = anonymous.request(
                    "POST",
                    "/api/v1/auth/login",
                    401 if attempt < 4 else 429,
                    body={"username": "operator", "password": "invalid"},
                )
            assert payload["code"] == "LOGIN_RATE_LIMITED"
            assert 1 <= int(headers["Retry-After"]) <= 60
            anonymous.request(
                "POST",
                "/api/v1/auth/login",
                429,
                headers={"X-Forwarded-For": "192.0.2.1", "X-Real-IP": "192.0.2.1"},
                body={"username": "manager", "password": config["passwords"]["manager"]},
            )
            print("PASS login rate limit, Retry-After and forwarding-header spoof rejection")

            container_python(
                """
import json, sys
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.auth.seed import seed_users
from app.core.db import get_catalog_engine
from app.models import AppUser, AuditEvent, Region
prefix = json.load(sys.stdin)["prefix"]
with Session(get_catalog_engine()) as db:
    accounts = {
        u.username: (u.id, u.password_hash, u.role)
        for u in db.scalars(select(AppUser).where(AppUser.username.in_(["operator", "manager"])))
    }
    assert len(accounts) == 2 and all(v[1].startswith("$argon2id$") for v in accounts.values())
    regions = db.scalar(select(func.count()).select_from(Region))
    seed_users(db)
    db.expire_all()
    assert accounts == {
        u.username: (u.id, u.password_hash, u.role)
        for u in db.scalars(select(AppUser).where(AppUser.username.in_(["operator", "manager"])))
    }
    assert db.scalar(select(func.count()).select_from(Region)) == regions
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.request_id.startswith(prefix))))
    assert sum(e.action == "LOGIN" for e in events) == 4
    assert sum(e.action == "LOGIN_FAILED" for e in events) == 6
    assert all(e.actor_id == e.entity_id and e.details is None for e in events)
    print("null")
""",
                {"prefix": run_id},
            )
            print("PASS persisted login audits and idempotent Argon2 user seeding")
        finally:
            if session_ids:
                container_python(
                    """
import json, sys, uuid
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.core.db import get_catalog_engine
from app.models.auth import UserSession
with Session(get_catalog_engine()) as db:
    ids = [uuid.UUID(value) for value in json.load(sys.stdin)["ids"]]
    db.execute(delete(UserSession).where(UserSession.id.in_(ids)))
    db.commit()
print("null")
""",
                    {"ids": sorted(session_ids)},
                )


if __name__ == "__main__":
    main()
