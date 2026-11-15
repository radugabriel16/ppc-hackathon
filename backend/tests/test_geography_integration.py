import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_catalog_db, get_catalog_engine
from app.files.schemas import OutageRecordMetadata
from app.files.service import linked_region
from app.main import create_app
from app.models.files import File
from app.models.geography import NetworkAsset
from app.models.issues import MapIssue
from app.models.metering import Meter, MeterReading

pytestmark = pytest.mark.integration
START = datetime(1985, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def geography():
    app = create_app()
    with get_catalog_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection) as db:
            app.dependency_overrides[get_catalog_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="OPERATOR")
            with TestClient(app, base_url="https://localhost") as client:
                yield db, client, app
        transaction.rollback()


def assert_partition(db):
    rows = db.execute(text("""
        SELECT r.code, count(s.id), bool_and(
            ST_Covers(ST_Buffer(b.geometry,1e-10),s.geometry)
            AND ST_Area(ST_Difference(s.geometry,b.geometry))<1e-12),
            bool_and(ST_IsValid(s.geometry) AND NOT ST_IsEmpty(s.geometry)
                     AND ST_SRID(s.geometry)=4326 AND ST_GeometryType(s.geometry)='ST_MultiPolygon'),
            ST_Area(ST_SymDifference(r.geometry,ST_UnaryUnion(ST_Collect(s.geometry)))) < 1e-10,
            ST_Covers(ST_Buffer(b.geometry,1e-10),r.geometry)
        FROM regions r JOIN subregions s ON s.region_id=r.id
        CROSS JOIN national_boundaries b
        GROUP BY r.id,b.geometry ORDER BY r.code
    """)).all()
    assert len(rows) == 3
    assert all(row[1] == 6 and all(row[2:]) for row in rows)
    assert db.scalar(text("""
        SELECT count(*) FROM subregions a JOIN subregions b ON a.id<b.id
        WHERE ST_Area(ST_Intersection(a.geometry,b.geometry))>1e-10
    """)) == 0


def test_border_partition_idempotence_and_history_preserved(geography):
    from fixtures.geography import seed_geography

    db, client, _ = geography
    assert_partition(db)
    before = db.execute(text("""
        SELECT count(*),sum(energy_kwh),min(interval_start),max(interval_end)
        FROM meter_readings
    """)).one()
    ids = db.execute(text("SELECT id,code FROM subregions ORDER BY code")).all()
    seed_geography(db)
    seed_geography(db)
    assert_partition(db)
    assert ids == db.execute(text("SELECT id,code FROM subregions ORDER BY code")).all()
    assert before == db.execute(text("""
        SELECT count(*),sum(energy_kwh),min(interval_start),max(interval_end)
        FROM meter_readings
    """)).one()
    regions = client.get("/api/v1/regions").json()["items"]
    assert len(regions) == 3
    assert all(len(r["subregions"]) == 6 and r["geometry"]["type"] == "MultiPolygon"
               for r in regions)
    for layer, count in (("REGIONS", 3), ("SUBREGIONS", 18)):
        response = client.get("/api/v1/map/features", params={"layer": layer})
        assert response.status_code == 200, response.text
        assert len(response.json()["features"]) == count
    assert db.scalar(text("SELECT count(*) FROM meters WHERE subregion_id IS NULL")) == 0
    assert db.scalar(text("SELECT count(*) FROM files WHERE subregion_id IS NULL")) == 0
    assert db.scalar(text("SELECT count(*) FROM map_issues WHERE subregion_id IS NULL")) == 0


def test_empty_grid_cells_are_resplit_into_six_nonempty_parts(geography, monkeypatch):
    from fixtures import geography as seed

    db, _, _ = geography
    monkeypatch.setattr(seed, "SQUARES", {"BANAT": (10, 30, 22.7, 46.25)})
    seed.seed_geography(db)
    assert_partition(db)


def test_spatial_boundary_assignment_links_and_filters(geography, monkeypatch):
    db, client, app = geography
    parent, first, second, boundary = db.execute(text("""
        SELECT a.region_id,a.id,b.id,ST_AsEWKT(ST_PointOnSurface(
            ST_Intersection(a.geometry,b.geometry)))
        FROM subregions a JOIN subregions b ON a.region_id=b.region_id AND a.code<b.code
        WHERE ST_Dimension(ST_Intersection(a.geometry,b.geometry))=1
        ORDER BY a.code,b.code LIMIT 1
    """)).one()
    expected = db.scalar(text("SELECT covered_subregion(ST_GeomFromEWKT(:g),:p)"),
                         {"g": boundary, "p": parent})
    assert expected in (first, second)
    assert db.scalar(text("""
        SELECT bool_and(ST_Covers(geometry,ST_GeomFromEWKT(:g)))
        FROM subregions WHERE id IN (:a,:b)
    """), {"g": boundary, "a": first, "b": second})
    records = []
    for index, subregion in enumerate((expected, second if expected == first else first)):
        location = boundary if index == 0 else db.scalar(text(
            "SELECT ST_AsEWKT(ST_PointOnSurface(geometry)) FROM subregions WHERE id=:id"
        ), {"id": subregion})
        asset = NetworkAsset(
            id=uuid.uuid4(), code=f"geo-{uuid.uuid4()}", name="Spatial filter test",
            region_id=parent, type="TRANSFORMER", geometry=location,
        )
        db.add(asset)
        db.flush()
        meter = Meter(id=uuid.uuid4(), external_code=f"geo-{uuid.uuid4()}", asset_id=asset.id)
        file = File(
            id=uuid.uuid4(), region_id=parent, category="METER_READING",
            original_name="spatial-test", media_type="application/json", size_bytes=1,
            sha256="0" * 64, storage_backend="db", storage_locator="spatial-test",
            status="READY", created_at=START,
        )
        issue = MapIssue(
            id=uuid.uuid4(), asset_id=asset.id, location=location,
            description="Spatial filter test", severity="LOW", status="OPEN", created_at=START,
        )
        db.add_all([meter, file, issue])
        db.flush()
        db.add(MeterReading(
            meter_id=meter.id, file_id=file.id, reading_key=str(uuid.uuid4()), seq=1,
            interval_start=START, interval_end=START + timedelta(hours=1),
            energy_kwh=3, received_at=START,
        ))
        db.flush()
        for row in (asset, meter, file, issue):
            db.refresh(row)
            assert row.subregion_id == subregion
        records.append((asset, meter, file, issue))
    selected, other = records
    params = {"subregionId": str(expected), "size": 100}
    for path, key, row in (
        ("assets", "items", selected[0]), ("meters", "items", selected[1]),
        ("files", "items", selected[2]), ("map-issues", "items", selected[3]),
    ):
        response = client.get(f"/api/v1/{path}", params={
            **params, **({"includeMeterReadings": True} if path == "files" else {}),
        })
        assert response.status_code == 200, response.text
        ids = {x["id"] for x in response.json()[key]}
        assert str(row.id) in ids
        assert str(other[("assets", "meters", "files", "map-issues").index(path)].id) not in ids
        mismatch = client.get(f"/api/v1/{path}", params={**params, "regionId": str(uuid.uuid4())})
        assert mismatch.json()[key] == []
        assert client.get(f"/api/v1/{path}", params={"subregionId": "invalid"}).status_code == 422
    issues = client.get("/api/v1/map/features", params={**params, "layer": "ISSUES"}).json()
    assert str(selected[3].id) in {x["properties"]["id"] for x in issues["features"]}
    assert str(other[3].id) not in {x["properties"]["id"] for x in issues["features"]}
    stats = client.get("/api/v1/stats/meters", params={
        **params, "from": START.isoformat(), "to": (START + timedelta(days=1)).isoformat(),
    }).json()
    assert [row["id"] for row in stats["meters"]] == [str(selected[1].id)]
    monkeypatch.setattr(app.state.forecast, "get", lambda db, segment, origin: {
        "segmentId": segment, "forecasts": [], "meters": [],
    })
    forecast = client.get("/api/v1/stats/forecast", params={**params, "origin": "2026-05-14"})
    assert forecast.status_code == 200, forecast.text
    ids = {row["segmentId"] for row in forecast.json()["items"]}
    assert str(selected[0].id) in ids and str(other[0].id) not in ids
    metadata = OutageRecordMetadata(
        category="OUTAGE_RECORD", assetId=selected[0].id, regionId=expected,
        startedAt=START, severity="LOW",
    )
    assert linked_region(db, metadata) == parent
    metadata.region_id = other[0].subregion_id
    with pytest.raises(HTTPException) as caught:
        linked_region(db, metadata)
    assert caught.value.status_code == 422
