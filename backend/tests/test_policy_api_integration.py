import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.auth import UserSession
from app.models.enums import FileCategory

pytestmark = pytest.mark.integration
PATH = "/api/v1/admin/policies"


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = get_settings()
    policy_path = tmp_path / "policies.yaml"
    policy_path.write_text(Path(settings.policies_path).read_text())
    monkeypatch.setattr(settings, "policies_path", str(policy_path))
    request_id = f"step5-{uuid.uuid4().hex}"
    app = create_app()
    session_ids = []
    try:
        with TestClient(
            app, base_url=str(settings.app_origin).rstrip("/"),
            headers={"Origin": str(settings.app_origin).rstrip("/"), "X-Request-Id": request_id},
        ) as client:
            def login(username):
                response = client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": username,
                        "password": (Path(settings.secrets_dir) / f"{username}_password").read_text().strip(),
                    },
                )
                assert response.status_code == 200
                session_ids.append(uuid.UUID(client.cookies[settings.session_cookie_name].split(".")[0]))
                return {"X-CSRF-Token": client.cookies["filegrid_csrf"]}

            yield client, app.state.policy_manager, policy_path, request_id, login
    finally:
        with Session(get_catalog_engine()) as db:
            db.execute(delete(UserSession).where(UserSession.id.in_(session_ids)))
            db.execute(delete(AuditEvent).where(AuditEvent.request_id == request_id))
            db.commit()


def test_reload_reuses_auth_roles_csrf_and_commits_audit(api):
    client, manager, path, request_id, login = api
    assert client.get(PATH).status_code == 401
    assert client.post(f"{PATH}/reload").status_code == 403
    headers = login("operator")
    assert client.get(PATH).status_code == 403
    assert client.post(f"{PATH}/reload", headers=headers).status_code == 403
    headers = login("manager")
    assert client.post(f"{PATH}/reload").status_code == 403
    assert client.post(
        f"{PATH}/reload", headers={**headers, "Origin": "https://untrusted.invalid"}
    ).status_code == 403

    raw = yaml.safe_load(path.read_text())
    raw["categories"]["OUTAGE_RECORD"]["maxConcurrency"] = 3
    path.write_text(yaml.safe_dump(raw))
    response = client.post(f"{PATH}/reload", headers=headers)
    assert response.status_code == 200
    assert response.json()["categories"]["OUTAGE_RECORD"]["maxConcurrency"] == 3
    assert manager.bulkheads[FileCategory.OUTAGE_RECORD].total_tokens == 3
    assert client.get(PATH).json() == response.json()
    with Session(get_catalog_engine()) as db:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.request_id == request_id, AuditEvent.action == "POLICIES_RELOADED"
            )
        )
        assert event.actor_id is not None
        assert event.details["categories"]["OUTAGE_RECORD"]["maxConcurrency"] == 3


@pytest.mark.parametrize(
    "invalid",
    [
        "categories: [",
        "[]",
        "categories: {}",
        ("OUTAGE_RECORD", "fallback", "ftp"),
        ("METER_READING", "maxSizeBytes", 1048577),
        ("OUTAGE_RECORD", "resumable", True),
    ],
)
def test_invalid_reload_keeps_previous_config_and_has_no_success_audit(api, invalid):
    client, manager, path, request_id, login = api
    headers = login("manager")
    previous = manager.config
    if isinstance(invalid, str):
        path.write_text(invalid)
    else:
        category, field, value = invalid
        raw = yaml.safe_load(path.read_text())
        raw["categories"][category][field] = value
        path.write_text(yaml.safe_dump(raw))
    response = client.post(f"{PATH}/reload", headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_POLICIES"
    assert response.json()["requestId"] == request_id
    assert manager.config is previous
    assert client.get(PATH).json() == previous.model_dump(mode="json", by_alias=True)
    with Session(get_catalog_engine()) as db:
        assert db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.request_id == request_id, AuditEvent.action == "POLICIES_RELOADED"
            )
        ) is None
