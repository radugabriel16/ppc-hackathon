import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import sign_session_id
from app.core.db import get_catalog_db, get_catalog_engine
from app.core.settings import get_settings
from app.main import create_app
from app.models.auth import AppUser, UserSession
from app.models.enums import FileCategory, FileStatus, StorageBackend
from app.models.files import File
from app.models.geography import NetworkAsset, Region
from app.models.jobs import ScenarioRun, StorageOperation
from app.models.metering import Meter, MeterReading
from app.models.outages import Outage

pytestmark = pytest.mark.integration
PATHS = ("storage-benchmark", "recommendations", "meters", "outages/hotspots")
START = datetime(1980, 1, 1, tzinfo=timezone.utc)
PARAMS = {"from": START.isoformat(), "to": (START + timedelta(days=3)).isoformat()}


@pytest.fixture
def stats():
    settings = get_settings()
    app = create_app()
    with get_catalog_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection) as db:
            regions = db.scalars(select(Region).order_by(Region.code)).all()
            assets = [
                db.scalar(select(NetworkAsset).where(NetworkAsset.region_id == r.id))
                for r in regions[:2]
            ]
            meters = []

            def file(category, asset):
                row = File(
                    id=uuid.uuid4(), region_id=asset.region_id, category=category,
                    original_name="stats-test.json", media_type="application/json",
                    size_bytes=1, sha256="0" * 64, storage_backend=StorageBackend.db,
                    storage_locator="stats-test", status=FileStatus.READY,
                    created_at=START,
                )
                db.add(row)
                db.flush()
                return row.id

            for index, asset in enumerate(assets):
                meter = Meter(
                    id=uuid.uuid4(), external_code=f"stats-{uuid.uuid4().hex}", asset_id=asset.id,
                )
                db.add(meter)
                db.flush()
                meters.append(meter)
                for seq, (hours, energy) in enumerate(((0, "1.25"), (1, "2.75"), (48, "0"))):
                    start = START + timedelta(hours=hours)
                    db.add(MeterReading(
                        meter_id=meter.id, reading_key=str(uuid.uuid4()), seq=seq,
                        interval_start=start, interval_end=start + timedelta(minutes=15),
                        energy_kwh=Decimal(energy) * (index + 1),
                        file_id=file(FileCategory.METER_READING, asset), received_at=START,
                    ))
            for asset, start, end in (
                (assets[0], START - timedelta(hours=1), START + timedelta(hours=1)),
                (assets[0], START + timedelta(days=2), None),
                (assets[1], START + timedelta(hours=2), START + timedelta(hours=2, minutes=30)),
            ):
                db.add(Outage(
                    asset_id=asset.id, file_id=file(FileCategory.OUTAGE_RECORD, asset),
                    started_at=start, ended_at=end, severity="HIGH",
                ))
            peak = ScenarioRun(
                id=uuid.uuid4(), kind="test", profile="peak", started_at=START,
            )
            db.add(peak)
            db.flush()
            for storage, duration, outcome, scenario in (
                (StorageBackend.db, 100, "success", None),
                (StorageBackend.db, 300, "error", None),
                (StorageBackend.s3, 500, "success", None),
                (StorageBackend.db, 50, "success", peak.id),
            ):
                db.add(StorageOperation(
                    category=FileCategory.METER_READING, storage=storage,
                    operation="put", bytes=1048576 if outcome == "success" else 0,
                    duration_ms=duration, outcome=outcome, occurred_at=START,
                    scenario_run_id=scenario,
                ))
            db.flush()

            def session_db():
                yield db

            app.dependency_overrides[get_catalog_db] = session_db
            with TestClient(app, base_url="https://localhost") as client:
                def authenticate(role="operator"):
                    user = db.scalar(select(AppUser).where(AppUser.username == role))
                    now = datetime.now(timezone.utc)
                    session = UserSession(
                        id=uuid.uuid4(), user_id=user.id, csrf_token=uuid.uuid4().hex,
                        created_at=now, expires_at=now + timedelta(hours=1),
                    )
                    db.add(session)
                    db.flush()
                    client.cookies.set(settings.session_cookie_name, sign_session_id(session.id))

                yield client, authenticate, regions, meters, assets
        transaction.rollback()


def get(client, path, **params):
    response = client.get("/api/v1/stats/" + path, params={**PARAMS, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_daily_energy_region_filter_pagination_and_gaps(stats):
    client, auth, regions, meters, _ = stats
    auth()
    all_meters = get(client, "meters")
    assert all_meters["totalElements"] == 2
    assert sum(r["kWh"] for m in all_meters["meters"] for r in m["readings"]) == 12
    one = get(client, "meters", regionId=str(regions[0].id))
    assert one["totalElements"] == 1
    meter = one["meters"][0]
    assert meter["id"] == str(meters[0].id)
    assert meter["regionCode"] == regions[0].code
    assert meter["intervalMinutes"] == 1440
    assert [r["kWh"] for r in meter["readings"]] == [4, 0]
    assert [r["anomaly"] for r in meter["readings"]] == [None, "zero"]
    assert meter["readings"][1]["timestamp"] == "1980-01-03T00:00:00Z"
    assert get(client, "meters", size=1, page=1)["totalPages"] == 2
    assert get(client, "meters", size=1, page=2)["meters"] == []
    assert get(client, "meters", regionId=str(uuid.uuid4()))["meters"] == []
    assert get(client, "meters", size=1000)["size"] == 100
    partial = get(client, "meters", regionId=str(regions[0].id), **{
        "from": "1980-01-01T01:00:00Z", "to": "1980-01-03T00:00:00Z",
    })
    assert [r["kWh"] for r in partial["meters"][0]["readings"]] == [2.75]


def test_hotspots_count_clipped_duration_regions_and_point_geometry(stats):
    client, auth, regions, _, assets = stats
    auth()
    features = get(client, "outages/hotspots")["features"]
    assert [r["properties"]["outageCount"] for r in features] == [2, 1]
    assert [r["properties"]["durationMinutes"] for r in features] == [1500, 30]
    assert features[0]["properties"]["id"] == str(assets[0].id)
    assert features[0]["geometry"]["type"] == "Point"
    assert len(features[0]["geometry"]["coordinates"]) == 2
    filtered = get(client, "outages/hotspots", regionId=str(regions[1].id))
    assert len(filtered["features"]) == 1
    assert filtered["features"][0]["properties"]["regionCode"] == regions[1].code
    assert get(client, "outages/hotspots", size=1, page=2)["features"] == []


def test_benchmark_observations_and_data_backed_recommendation(stats):
    client, auth, *_ = stats
    auth()
    result = get(client, "storage-benchmark")
    assert result["totalElements"] == 3
    normal = next(r for r in result["rows"] if r["storage"] == "db" and r["profile"] == "normal")
    assert normal["p50Ms"] == 200
    assert normal["p95Ms"] == 290
    assert normal["p99Ms"] == 298
    assert normal["throughputMiBps"] == 2.5
    assert normal["errorRate"] == 0.5
    recommendations = get(client, "recommendations")["items"]
    assert len(recommendations) == 1
    assert recommendations[0]["storage"] == "db"  # peak has no errors and p95=50
    assert "peak" in recommendations[0]["reason"]
    assert get(client, "storage-benchmark", size=1, page=1)["totalElements"] == 3


@pytest.mark.parametrize("path,key", zip(PATHS, ("rows", "items", "meters", "features")))
def test_auth_roles_empty_and_invalid_ranges(stats, path, key):
    client, auth, *_ = stats
    for headers in ({}, {"Authorization": "Bearer not-a-session"}):
        response = client.get("/api/v1/stats/" + path, headers=headers)
        assert response.status_code == 401
        assert {"code", "message", "fieldErrors", "requestId"} == response.json().keys()
    for role in ("operator", "manager"):
        auth(role)
        assert get(client, path)["totalElements"] > 0
    assert get(client, path, **{
        "from": "1979-01-01T00:00:00Z", "to": "1979-01-02T00:00:00Z",
    })[key] == []
    for params in (
        {"from": PARAMS["to"], "to": PARAMS["from"]},
        {"from": PARAMS["to"], "to": PARAMS["to"]},
        {"from": "invalid"}, {"from": "1980-01-01T00:00:00"},
        {"from": "1978-01-01T00:00:00Z"}, {"size": 0}, {"page": -1},
    ):
        response = client.get("/api/v1/stats/" + path, params={**PARAMS, **params})
        assert response.status_code == 422, response.text
        assert response.json()["requestId"] == response.headers["X-Request-Id"]
    if path in ("meters", "outages/hotspots"):
        assert client.get("/api/v1/stats/" + path, params={"regionId": "invalid"}).status_code == 422
    # Neither authenticated role is forbidden from these contracted read endpoints.
    assert client.get("/api/v1/stats/forecast").status_code == 404


@pytest.mark.parametrize("role", ("ingest", "worker"))
def test_stats_routes_are_files_only(monkeypatch, role):
    monkeypatch.setattr(get_settings(), "role", role)
    assert not any(route.path.startswith("/api/v1/stats") for route in create_app().routes)
