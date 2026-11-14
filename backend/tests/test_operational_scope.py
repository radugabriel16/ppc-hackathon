import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_catalog_db, get_catalog_engine
from app.core.settings import get_settings
from app.jobs.missing_documents import sync_missing_documents
from app.main import create_app
from app.models.alerts import Alert
from app.models.auth import AppUser
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType
from app.models.forecast import ForecastRun, SegmentThreshold
from app.models.geography import NetworkAsset, Subregion
from app.models.inspections import VideoInspection
from app.models.issues import MapIssue
from app.models.metering import Meter

pytestmark = pytest.mark.integration
BASE = "/api/v1"


@pytest.fixture
def operational():
    app = create_app()
    with get_catalog_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as db:
            user = db.scalar(select(AppUser).where(AppUser.username == "manager"))
            identity = SimpleNamespace(id=user.id, role="MANAGER")
            area = db.scalar(select(Subregion).where(Subregion.code == "MUNTENIA-5"))
            for segment_id in db.scalars(select(Subregion.id)):
                config = db.get(SegmentThreshold, segment_id)
                if config is None:
                    db.add(SegmentThreshold(
                        segment_id=segment_id, daily_energy_kwh=400, source="MANUAL",
                    ))
                else:
                    config.daily_energy_kwh = 400
                    config.source = "MANUAL"
                    config.calibration = None
            db.flush()
            asset = db.scalar(select(NetworkAsset).where(NetworkAsset.subregion_id == area.id))
            point = json.loads(db.scalar(select(func.ST_AsGeoJSON(
                func.ST_PointOnSurface(Subregion.geometry)
            )).where(Subregion.id == area.id)))
            app.dependency_overrides[get_catalog_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: identity
            origin = str(get_settings().app_origin).rstrip("/")
            with TestClient(app, base_url=origin, headers={
                "Origin": origin, "X-CSRF-Token": "operational-test",
            }) as client:
                client.cookies.set("filegrid_csrf", "operational-test")
                yield SimpleNamespace(
                    db=db, client=client, app=app, user=identity,
                    area=area, asset=asset, point=point,
                )
        transaction.rollback()


def create(data, **changes):
    return data.client.post(BASE + "/map-issues", json={
        "assetId": str(data.asset.id), "location": data.point,
        "severity": "HIGH", **changes,
    })


def test_historical_issues_retained_but_hidden_from_list_map_stats(operational):
    d = operational
    response = create(d)
    assert response.status_code == 201, response.text
    issue = d.db.get(MapIssue, uuid.UUID(response.json()["id"]))
    issue.is_historical = True
    d.db.commit()
    d.user.role = "OPERATOR"
    for path in ("/map-issues", "/map/features?layer=ISSUES", "/stats/issues"):
        response = d.client.get(BASE + path)
        assert response.status_code == 200
        assert str(issue.id) not in response.text
        separator = "&" if "?" in path else "?"
        assert d.client.get(BASE + path + separator + "includeHistorical=true").status_code == 403
    d.user.role = "MANAGER"
    all_issues = d.client.get(BASE + "/map-issues?includeHistorical=true&size=100").json()
    assert str(issue.id) in {row["id"] for row in all_issues["items"]}
    mapped = d.client.get(BASE + "/map/features?layer=ISSUES&includeHistorical=true").json()
    assert str(issue.id) in {row["properties"]["id"] for row in mapped["features"]}
    default = d.client.get(BASE + "/stats/issues").json()["items"]
    included = d.client.get(BASE + "/stats/issues?includeHistorical=true").json()["items"]
    assert sum(row["count"] for row in included) > sum(row["count"] for row in default)
    assert d.db.get(MapIssue, issue.id).is_historical


def video_file(d, status="READY"):
    from app.models.files import File

    file = File(
        region_id=d.area.region_id, category="DRONE_VIDEO", original_name="test.mp4",
        media_type="video/mp4", size_bytes=1, sha256="0" * 64, storage_backend="s3",
        storage_locator=str(uuid.uuid4()), status=status,
        created_at=datetime.now(timezone.utc),
    )
    d.db.add(file)
    d.db.flush()
    return file


def test_issue_types_titles_video_links_and_query_filters(operational):
    d = operational
    manual = create(d).json()
    assert manual["type"] == "OUTAGE_REPORT"
    assert d.area.name in manual["title"] and d.area.name in manual["description"]
    mapped = d.client.get(BASE + "/map/features?layer=ISSUES").json()["features"]
    feature = next(row for row in mapped if row["properties"]["id"] == manual["id"])
    assert feature["properties"]["title"] == manual["title"]
    assert not {"clientName", "email", "description"} & set(feature["properties"])
    file = video_file(d)
    video = VideoInspection(asset_id=d.asset.id, file_id=file.id, recorded_at=datetime.now(timezone.utc))
    d.db.add(video)
    d.db.flush()
    for kind in ("OUTAGE_VIDEO", "DRONE_DETECTED"):
        response = create(d, type=kind, fileId=str(file.id), videoInspectionId=str(video.id))
        assert response.status_code == 201, response.text
        issue = response.json()
        assert issue["type"] == kind and issue["fileId"] == str(file.id)
        assert issue["title"] and issue["description"]
        filters = {
            "type": kind, "status": "OPEN", "segmentId": str(d.area.id),
            "regionId": str(d.area.region_id), "from": "2026-01-01T00:00:00Z",
            "to": "2099-01-01T00:00:00Z",
        }
        rows = d.client.get(BASE + "/map-issues", params=filters).json()["items"]
        assert [row["id"] for row in rows] == [issue["id"]]
        assert not d.client.get(BASE + "/map-issues", params={
            **filters, "status": "RESOLVED",
        }).json()["items"]
    assert create(d, type="OUTAGE_VIDEO").status_code == 422
    assert create(d, type="ML_FORECAST").status_code == 422
    assert create(d, type="MISSING_DOCUMENTS").status_code == 422
    assert create(d, type="OUTAGE_VIDEO", fileId=str(uuid.uuid4())).status_code == 422
    assert d.client.get(BASE + "/map-issues?from=2026-11-02T00:00:00Z&to=2026-11-01T00:00:00Z").status_code == 422


def test_exact_point_scope_validation_and_meter_client_links(operational):
    d = operational
    precise = {"type": "Point", "coordinates": [
        d.point["coordinates"][0] + 0.000000123456789123,
        d.point["coordinates"][1] + 0.000000234567891234,
    ]}
    response = create(d, location=precise)
    assert response.status_code == 201, response.text
    assert response.json()["location"] == precise
    mapped = d.client.get(BASE + "/map/features?layer=ISSUES").json()["features"]
    feature = next(row for row in mapped if row["properties"]["id"] == response.json()["id"])
    assert feature["geometry"] == precise
    meter = d.db.scalar(select(Meter).join(Client).where(
        Meter.subregion_id == d.area.id, Client.region_id == d.area.region_id,
    ))
    point = json.loads(d.db.scalar(select(func.ST_AsGeoJSON(Meter.location)).where(Meter.id == meter.id)))
    response = create(
        d, location=point, regionId=str(d.area.region_id), segmentId=str(d.area.id),
        meterId=str(meter.id), clientId=str(meter.client_id),
    )
    assert response.status_code == 201, response.text
    issue = response.json()
    assert issue["location"] == point
    assert issue["regionId"] == str(d.area.region_id) and issue["segmentId"] == str(d.area.id)
    assert issue["clientId"] == str(meter.client_id)
    assert d.db.scalar(text("SELECT ST_SRID(location) FROM map_issues WHERE id=:id"), {"id": issue["id"]}) == 4326
    assert d.client.get(BASE + "/map-issues", params={"clientId": str(meter.client_id)}).json()["items"]
    for point in ([2.35, 48.86], [30, 44], [23.6, 46.77]):
        assert create(d, location={"type": "Point", "coordinates": point}).status_code == 422
    assert create(d, regionId=str(uuid.uuid4())).status_code == 422
    assert create(d, segmentId=str(uuid.uuid4())).status_code == 422
    assert create(d, meterId=str(uuid.uuid4())).status_code == 422
    boundary = d.db.execute(text("""
        SELECT a.id,ST_AsGeoJSON(ST_PointOnSurface(ST_Intersection(a.geometry,b.geometry)))
        FROM subregions a JOIN subregions b ON a.region_id=b.region_id AND a.code<b.code
        WHERE a.region_id=:region AND ST_Dimension(ST_Intersection(a.geometry,b.geometry))=1
        ORDER BY a.code,b.code LIMIT 1
    """), {"region": d.area.region_id}).one()
    response = create(d, location=json.loads(boundary[1]), regionId=str(d.area.region_id))
    assert response.status_code == 201, response.text
    assert response.json()["location"] == json.loads(boundary[1])
    shared = d.db.scalar(text("""
        SELECT ST_AsGeoJSON(ST_PointOnSurface(ST_Intersection(a.geometry,b.geometry)))
        FROM regions a JOIN regions b ON a.code<b.code
        WHERE ST_Dimension(ST_Intersection(a.geometry,b.geometry))=1 LIMIT 1
    """))
    assert shared is not None
    point = json.loads(shared)
    chosen = d.db.scalar(text("""
        SELECT region_id FROM subregions
        WHERE id=covered_subregion(ST_SetSRID(ST_GeomFromGeoJSON(:point),4326))
    """), {"point": shared})
    asset = d.db.scalar(select(NetworkAsset).where(NetworkAsset.region_id == chosen))
    response = create(d, assetId=str(asset.id), location=point, regionId=str(chosen))
    assert response.status_code == 201, response.text
    assert response.json()["regionId"] == str(chosen)
    other = d.db.scalar(select(Subregion.region_id).where(Subregion.region_id != chosen))
    assert create(d, assetId=str(asset.id), location=point, regionId=str(other)).status_code == 422


def test_meter_topology_seed_is_idempotent_and_preserves_existing_rows(operational):
    from fixtures.meters import seed_meters

    d = operational
    before = d.db.execute(text("SELECT id,external_code,asset_id,client_id FROM meters ORDER BY id")).all()
    seed_meters(d.db)
    seed_meters(d.db)
    assert d.db.execute(text("SELECT id,external_code,asset_id,client_id FROM meters ORDER BY id")).all() == before
    assert len(before) == 144
    assert d.db.scalar(text("""
        SELECT bool_and(n=8) FROM (SELECT count(*) n FROM meters GROUP BY subregion_id) x
    """))
    assert d.db.scalar(text("""
        SELECT bool_and(ST_Covers(s.geometry,m.location) AND ST_SRID(m.location)=4326)
        FROM meters m JOIN subregions s ON s.id=m.subregion_id
    """))
    response = d.client.get(BASE + "/meters", params={
        "regionId": str(d.area.region_id), "segmentId": str(d.area.id),
    })
    assert response.status_code == 200, response.text
    assert response.json()["totalElements"] == 8
    assert all(row["location"]["type"] == "Point" for row in response.json()["items"])
    removed = d.db.scalar(select(Meter).where(
        Meter.subregion_id == d.area.id, Meter.external_code.startswith("RO-"),
    ).order_by(Meter.external_code))
    removed_id = removed.id
    d.db.delete(removed)
    d.db.flush()
    seed_meters(d.db)
    seed_meters(d.db)
    after = d.db.execute(text("SELECT id,external_code,asset_id,client_id FROM meters ORDER BY id")).all()
    assert len(after) == 144
    assert set(row for row in before if row[0] != removed_id) <= set(after)


def test_subregion_runtime_reads_only_scoped_meters_and_observations(operational, monkeypatch):
    from app.models.metering import MeterReading

    d = operational
    expected = {str(id) for id in d.db.scalars(select(Meter.id).where(Meter.subregion_id == d.area.id))}
    inside = next(iter(expected))
    outside = d.db.scalar(select(Meter.id).where(Meter.subregion_id != d.area.id))
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = datetime.combine(tomorrow - timedelta(days=2), datetime.min.time(), timezone.utc)
    for meter_id, energy in ((inside, 12), (outside, 99999)):
        file = video_file(d)
        d.db.add(MeterReading(
            meter_id=uuid.UUID(str(meter_id)), file_id=file.id,
            reading_key=f"scoped-{uuid.uuid4()}", seq=1,
            interval_start=start, interval_end=start + timedelta(hours=6),
            received_at=start + timedelta(hours=6, minutes=1), energy_kwh=energy,
        ))
    d.db.flush()
    captured = []

    def prediction(service, history, segment, *, as_of):
        import numpy as np

        assert set(history.meters.id) == expected
        assert set(history.meters.segment_id) == {str(d.area.id)}
        assert np.nansum(history.slots) == 12
        assert as_of.date() == tomorrow - timedelta(days=1)
        captured.append(segment)
        return {"forecasts": [], "meters": []}

    monkeypatch.setattr("app.forecast.service.predict", prediction)
    d.app.state.forecast.get_subregion(d.db, str(d.area.id), tomorrow)
    assert captured == [str(d.area.id)]


@pytest.mark.parametrize("scope", ["country", "region", "segment"])
def test_scoped_runs_dates_thresholds_dedup_alerts_and_persistence(operational, monkeypatch, scope):
    d = operational
    calls = []

    def forecast(db, segment, origin):
        assert threading.current_thread().name == "AnyIO worker thread"
        calls.append(segment)
        return {
            "segmentId": segment, "fallbackUsed": True, "meters": [],
            "forecasts": [
                {"date": (origin + timedelta(days=index)).isoformat(), "horizon": index + 1,
                 "predictedEnergyKwh": 500, "status": "READY", "fallbackUsed": True,
                 "expectedMeters": 8, "eligibleMeters": 8}
                for index in range(3)
            ],
        }

    monkeypatch.setattr(d.app.state.forecast, "get_subregion", forecast)
    body = {"scope": scope}
    if scope == "region":
        body["regionId"] = str(d.area.region_id)
    if scope == "segment":
        body["segmentId"] = str(d.area.id)
    response = d.client.post(BASE + "/forecast/runs", json=body)
    assert response.status_code == 201, response.text
    first = response.json()
    expected_count = {"country": 18, "region": 6, "segment": 1}[scope]
    assert len(calls) == expected_count and len(set(calls)) == expected_count
    expected = select(Subregion.id)
    if scope == "region":
        expected = expected.where(Subregion.region_id == d.area.region_id)
    if scope == "segment":
        expected = expected.where(Subregion.id == d.area.id)
    assert set(calls) == {str(id) for id in d.db.scalars(expected)}
    assert len(first["createdIssues"]) == expected_count * 3
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    assert [p["date"] for p in first["segments"][0]["forecasts"]] == [
        (tomorrow + timedelta(days=day)).isoformat() for day in range(3)
    ]
    assert all(p["excessKwh"] == 100 for row in first["segments"] for p in row["forecasts"])
    assert all("100.000 kWh" in issue["description"] and issue["type"] == "ML_FORECAST"
               for issue in first["createdIssues"])
    assert all(
        f"expected to exceed on {issue['forecastDate']} by 100.000 kWh" in issue["title"]
        for issue in first["createdIssues"]
    )
    count = d.db.scalar(select(func.count()).select_from(Alert))
    second = d.client.post(BASE + "/forecast/runs", json=body)
    assert second.status_code == 201, second.text
    assert second.json()["createdIssues"] == []
    assert d.db.scalar(select(func.count()).select_from(Alert)) == count
    assert d.client.get(BASE + "/forecast/runs/" + first["id"]).json() == first
    assert d.db.get(ForecastRun, uuid.UUID(first["id"])).status == "COMPLETED"


def test_run_validation_threshold_roles_and_durable_failure(operational, monkeypatch):
    from fastapi import HTTPException

    d = operational
    for body in (
        {"scope": "region"}, {"scope": "segment"},
        {"scope": "country", "regionId": str(d.area.region_id)},
        {"scope": "region", "regionId": str(d.area.region_id), "segmentId": str(d.area.id)},
    ):
        assert d.client.post(BASE + "/forecast/runs", json=body).status_code == 422
    assert d.client.post(BASE + "/forecast/runs", json={
        "scope": "segment", "segmentId": str(uuid.uuid4()),
    }).status_code == 404
    other = d.db.scalar(select(Subregion).where(Subregion.region_id != d.area.region_id))
    assert d.client.post(BASE + "/forecast/runs", json={
        "scope": "segment", "segmentId": str(other.id), "regionId": str(d.area.region_id),
    }).status_code == 422
    path = BASE + f"/forecast/thresholds/{d.area.id}"
    d.user.role = "OPERATOR"
    assert d.client.put(path, json={"dailyEnergyKwh": 1}).status_code == 403
    d.user.role = "MANAGER"
    assert d.client.put(path, json={"dailyEnergyKwh": 0}).status_code == 422
    assert d.client.put(path, json={"dailyEnergyKwh": 250}).status_code == 200
    assert float(d.db.get(SegmentThreshold, d.area.id).daily_energy_kwh) == 250
    assert d.db.get(SegmentThreshold, d.area.id).source == "MANUAL"
    assert len(d.client.get(BASE + "/forecast/thresholds").json()) == 18

    def fail(*args):
        raise HTTPException(503, "Model unavailable")

    monkeypatch.setattr(d.app.state.forecast, "get_subregion", fail)
    response = d.client.post(BASE + "/forecast/runs", json={
        "scope": "segment", "segmentId": str(d.area.id),
    })
    assert response.status_code == 503
    run = d.client.get(response.headers["Location"]).json()
    assert run["status"] == "FAILED" and run["error"]
    assert run["createdIssues"] == []


def test_history_threshold_excludes_incomplete_and_unavailable_days_and_preserves_override(operational):
    from fastapi import HTTPException
    from sqlalchemy import delete
    from app.forecast.thresholds import calibrate_threshold, threshold_for_run
    from app.models.files import File
    from app.models.metering import MeterReading

    d = operational
    as_of = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    start = as_of.replace(hour=0) - timedelta(days=28)
    meters = d.db.scalars(select(Meter.id).where(Meter.subregion_id == d.area.id)).all()
    d.db.execute(delete(MeterReading).where(
        MeterReading.meter_id.in_(meters), MeterReading.interval_start >= start,
        MeterReading.interval_start < as_of,
    ))
    files, readings = [], []
    for day in range(28):
        for meter in meters:
            for slot in range(4):
                if day == 27 and meter == meters[0] and slot == 3:
                    continue
                file_id = uuid.uuid4()
                left = start + timedelta(days=day, hours=6 * slot)
                end = left + timedelta(hours=6)
                files.append({
                    "id": file_id, "region_id": d.area.region_id, "category": "METER_READING",
                    "original_name": "threshold-test", "media_type": "application/json",
                    "size_bytes": 1, "sha256": "0" * 64, "storage_backend": "db",
                    "storage_locator": str(file_id), "status": "READY", "created_at": left,
                })
                readings.append({
                    "id": uuid.uuid4(), "meter_id": meter, "file_id": file_id,
                    "reading_key": str(uuid.uuid4()), "seq": day * 4 + slot,
                    "interval_start": left, "interval_end": end,
                    "energy_kwh": day + 1 if day < 26 else 100000,
                    "received_at": as_of + timedelta(hours=1) if day == 26 else end,
                })
    d.db.execute(File.__table__.insert(), files)
    d.db.execute(MeterReading.__table__.insert(), readings)
    config = d.db.get(SegmentThreshold, d.area.id)
    config.source = "UNCONFIGURED"
    d.db.flush()
    config = threshold_for_run(d.db, d.area.id, as_of)
    assert config.source == "HISTORY_P95"
    assert config.calibration["sampleDays"] == 26
    assert float(config.daily_energy_kwh) == pytest.approx(792 * 1.03)
    config.source, config.daily_energy_kwh, config.calibration = "MANUAL", 123, None
    d.db.flush()
    assert float(calibrate_threshold(d.db, d.area.id, as_of).daily_energy_kwh) == 123
    config.source = "UNCONFIGURED"
    d.db.execute(delete(MeterReading).where(
        MeterReading.meter_id.in_(meters),
        MeterReading.interval_start >= start + timedelta(days=13),
        MeterReading.interval_start < as_of,
    ))
    d.db.flush()
    with pytest.raises(HTTPException, match="14 complete"):
        threshold_for_run(d.db, d.area.id, as_of)


def test_missing_document_clients_case_filters_and_issue_lifecycle(operational):
    d = operational
    client = Client(
        region_id=d.area.region_id, external_code=f"checklist-{uuid.uuid4()}",
        name_enc=b"synthetic", email_enc=b"synthetic", client_type="RESIDENTIAL",
        location=f"SRID=4326;POINT({d.point['coordinates'][0]} {d.point['coordinates'][1]})",
    )
    d.db.add(client)
    d.db.flush()
    case = ConnectionCase(client_id=client.id, status="OPEN", opened_at=datetime.now(timezone.utc))
    d.db.add(case)
    d.db.flush()
    params = {"regionId": str(d.area.region_id), "segmentId": str(d.area.id)}
    sync_missing_documents(d.db)
    sync_missing_documents(d.db)
    rows = d.client.get(BASE + "/clients/missing-documents", params=params).json()["items"]
    row = next(row for row in rows if row["clientId"] == str(client.id))
    assert row["cases"][0]["caseId"] == str(case.id)
    assert row["cases"][0]["missingDocumentTypes"]
    issues = d.client.get(BASE + "/map-issues", params={
        **params, "clientId": str(client.id), "type": "MISSING_DOCUMENTS",
    }).json()["items"]
    assert len(issues) == 1 and issues[0]["caseId"] == str(case.id)
    cases = d.client.get(BASE + "/connection-cases", params={
        **params, "clientId": str(client.id), "status": "OPEN",
        "type": "MISSING_DOCUMENTS", "from": "2026-01-01T00:00:00Z",
    }).json()["items"]
    assert [row["id"] for row in cases] == [str(case.id)]
    case.status = "CLOSED"
    d.db.flush()
    rows = d.client.get(BASE + "/clients/missing-documents", params=params).json()["items"]
    assert str(client.id) in {row["clientId"] for row in rows}
    rows = d.client.get(BASE + "/clients/missing-documents", params={**params, "status": "OPEN"}).json()["items"]
    assert str(client.id) not in {row["clientId"] for row in rows}
    for document_type in d.db.scalars(select(DocumentType).where(DocumentType.required_for_connection)):
        file = video_file(d)
        file.category = "CONNECTION_DOCUMENT"
        d.db.add(ClientDocument(
            case_id=case.id, document_type_id=document_type.id, file_id=file.id,
            uploaded_at=datetime.now(timezone.utc),
        ))
    d.db.flush()
    sync_missing_documents(d.db)
    assert d.db.get(MapIssue, uuid.UUID(issues[0]["id"])).status == "RESOLVED"
    rows = d.client.get(BASE + "/clients/missing-documents", params=params).json()["items"]
    assert str(client.id) not in {row["clientId"] for row in rows}
    file.status = "CORRUPT"
    d.db.flush()
    sync_missing_documents(d.db)
    assert d.db.get(MapIssue, uuid.UUID(issues[0]["id"])).status == "OPEN"
