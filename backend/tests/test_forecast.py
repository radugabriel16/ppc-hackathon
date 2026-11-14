import json
import runpy
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.forecast.service import ForecastRuntime, load_model, predict
from app.main import create_app
from filegrid_forecast.core import History

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "model-ML/filegrid-model-handoff"
SEGMENT = "2955b0aa-ebdf-5453-ab7d-90cc043f04f1"
ORIGIN = pd.Timestamp("2026-11-14", tz="UTC")


@pytest.fixture(scope="module")
def service():
    service, error = load_model()
    assert error is None
    return service


@pytest.fixture(scope="module")
def golden_history(tmp_path_factory):
    directory = tmp_path_factory.mktemp("forecast-history")
    generator = runpy.run_path(str(ROOT / "model-ML/filegrid-history-v2/generate.py"))
    generator["generate"](directory)
    history = History.from_sqlite(
        directory / "history.sqlite", pd.Timestamp("2024-11-14", tz="UTC"), ORIGIN,
    )
    indexes = np.flatnonzero((history.meters.segment_id == SEGMENT).to_numpy())
    return History(
        history.meters.iloc[indexes].reset_index(drop=True), history.start, history.end,
        history.slots[:, indexes, :], history.arrival[:, indexes, :],
    )


def test_load_verified_model_and_refuse_missing_mismatch_before_deserialization(tmp_path, monkeypatch):
    import app.forecast.service as module
    from importlib.resources import files

    source = Path(str(files("filegrid_forecast")))
    shutil.copytree(source, tmp_path / "package")
    package = tmp_path / "package"
    model = package / "model/forecast_3d.joblib"
    assert load_model(package)[0] is not None
    called = []
    monkeypatch.setattr(module, "ForecastService", lambda path: called.append(path))
    model.write_bytes(model.read_bytes() + b"tampered")
    assert "SHA-256" in load_model(package)[1]
    model.unlink()
    assert "unavailable" in load_model(package)[1]
    assert not called
    runtime = ForecastRuntime(package)
    with pytest.raises(Exception) as caught:
        runtime.get(None, SEGMENT, ORIGIN.date())
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "FORECAST_UNAVAILABLE"


@pytest.mark.parametrize("filename,include", [
    ("segment-013.json", False), ("segment-013-with-meters.json", True),
])
def test_golden_output_matches_handoff(service, golden_history, filename, include):
    expected = json.loads((HANDOFF / "examples" / filename).read_text())
    actual = service.predict_segment(golden_history, SEGMENT, include_meters=include)
    assert actual == expected


def test_insufficient_history_baseline_and_missing_meter_is_not_zero(service, golden_history):
    slots = np.full_like(golden_history.slots, np.nan)
    slots[-3:] = golden_history.slots[-3:]
    history = History(
        golden_history.meters, golden_history.start, golden_history.end,
        slots, golden_history.arrival,
    )
    result = predict(service, history, SEGMENT)
    assert result["fallbackUsed"] is True
    assert "baseline" in result["method"]
    expected = np.mean(np.sum(slots[-3:], axis=2), axis=0).sum()
    assert result["forecasts"][0]["predictedEnergyKwh"] == pytest.approx(expected, abs=1e-5)
    assert all(p["fallbackUsed"] for m in result["meters"] for p in m["forecasts"])
    slots[:, 0] = np.nan
    result = predict(service, history, SEGMENT)
    assert all(p["predictedEnergyKwh"] is None and p["status"] == "INSUFFICIENT_DATA"
               for p in result["forecasts"])
    assert result["forecasts"][0]["eligibleMeters"] == 6
    assert result["meters"][0]["forecasts"][0]["predictedEnergyKwh"] is None
    slots[:] = np.nan
    result = predict(service, history, SEGMENT)
    assert all(p["predictedEnergyKwh"] is None and p["eligibleMeters"] == 0
               for p in result["forecasts"])


def test_catalog_topology_does_not_change_per_meter_model_predictions(service, golden_history):
    expected = service.predict_segment(golden_history, SEGMENT, include_meters=True)
    history = History(
        golden_history.meters.iloc[:2], golden_history.start, golden_history.end,
        golden_history.slots[:, :2], golden_history.arrival[:, :2],
    )
    actual = service.predict_segment(history, SEGMENT, include_meters=True, expected_meters=2)
    assert actual["meters"] == expected["meters"][:2]
    assert actual["forecasts"][0]["predictedEnergyKwh"] == pytest.approx(
        sum(m["forecasts"][0]["predictedEnergyKwh"] for m in actual["meters"]), abs=1e-6,
    )
    with pytest.raises(ValueError, match="registered"):
        service.predict_segment(history, SEGMENT)


def test_tomorrow_bridge_preserves_observations_and_uses_model(service, golden_history):
    from app.forecast.service import bridge_intraday

    slots = golden_history.slots.copy()
    slots[-1, :, 2:] = np.nan
    history = History(
        golden_history.meters, golden_history.start, golden_history.end,
        slots, golden_history.arrival.copy(),
    )
    as_of = (history.end - pd.Timedelta(hours=10)).to_pydatetime()
    bridged, mask = bridge_intraday(history, as_of)
    assert mask.sum() == len(history.meters) * 2
    np.testing.assert_array_equal(bridged.slots[-1, :, :2], slots[-1, :, :2])
    np.testing.assert_allclose(
        bridged.slots[-1, :, 2:], np.median(slots[[-8, -15, -22, -29], :, 2:], axis=0),
    )
    assert np.isnan(history.slots[-1, :, 2:]).all()
    result = predict(service, history, SEGMENT, as_of=as_of)
    assert result["bridged"] and result["bridge"]["persistedAsReadings"] is False
    assert result["method"] == "hgb_smooth" and not result["fallbackUsed"]
    assert all(p["bridged"] and not p["fallbackUsed"] for p in result["forecasts"])
    expected = service.predict_segment(bridged, SEGMENT, include_meters=True)
    assert [p["predictedEnergyKwh"] for p in result["forecasts"]] == [
        p["predictedEnergyKwh"] for p in expected["forecasts"]
    ]


def test_bridge_does_not_hide_old_gaps_or_invent_sparse_profiles(service, golden_history):
    slots = golden_history.slots.copy()
    slots[-1, :, 3] = np.nan
    slots[-2, 0, 0] = np.nan
    slots[[-8, -15, -22], 1, 3] = np.nan
    history = History(
        golden_history.meters, golden_history.start, golden_history.end,
        slots, golden_history.arrival,
    )
    as_of = (history.end - pd.Timedelta(hours=1)).to_pydatetime()
    result = predict(service, history, SEGMENT, as_of=as_of)
    assert result["meters"][0]["forecasts"][0]["fallbackUsed"]
    observed = history.snapshot(history.end)[-28:, 0]
    expected_baseline = observed[np.isfinite(observed)][-7:].mean()
    assert result["meters"][0]["forecasts"][0]["predictedEnergyKwh"] == pytest.approx(
        expected_baseline, abs=1e-6,
    )
    assert result["meters"][1]["forecasts"][0]["fallbackUsed"]
    assert not result["meters"][2]["forecasts"][0]["fallbackUsed"]
    historical = predict(service, history, SEGMENT, as_of=history.end.to_pydatetime())
    assert not historical["bridged"]
    assert all(m["forecasts"][0]["fallbackUsed"] for m in historical["meters"])


def test_unknown_client_type_uses_model_without_inventing_metadata(service, golden_history):
    metadata = golden_history.meters.copy()
    metadata.loc[0, "client_type"] = None
    history = History(
        metadata, golden_history.start, golden_history.end,
        golden_history.slots, golden_history.arrival,
    )
    result = predict(service, history, SEGMENT)
    assert not result["fallbackUsed"] and result["method"] == "hgb_smooth"
    assert result["unknownClientTypeMeters"] == 1
    assert result["meters"][0]["clientTypeUnknown"]
    assert metadata.loc[0, "client_type"] is None


def test_eight_meter_subregion_uses_same_per_meter_model_and_sums(service, golden_history):
    metadata = pd.concat([golden_history.meters, golden_history.meters.iloc[:1]], ignore_index=True)
    metadata.loc[7, "id"] = str(uuid.uuid4())
    metadata.loc[7, "external_code"] = "RO-MUNTENIA-1-008"
    subregion = str(uuid.uuid4())
    metadata["segment_id"] = subregion
    metadata["segment"] = "MUNTENIA-1"
    history = History(
        metadata, golden_history.start, golden_history.end,
        np.concatenate([golden_history.slots, golden_history.slots[:, :1]], axis=1),
        np.concatenate([golden_history.arrival, golden_history.arrival[:, :1]], axis=1),
    )
    result = predict(service, history, subregion)
    assert result["fallbackUsed"] is False
    assert result["segmentId"] == subregion
    assert len(result["meters"]) == 8
    for day, point in enumerate(result["forecasts"]):
        assert point["expectedMeters"] == point["eligibleMeters"] == 8
        assert point["predictedEnergyKwh"] == pytest.approx(sum(
            meter["forecasts"][day]["predictedEnergyKwh"] for meter in result["meters"]
        ), abs=1e-5)


def test_authentication_and_invalid_parameters(monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "role", "files")
    app = create_app()
    from app.auth.dependencies import get_current_session
    from fastapi import HTTPException

    def no_session():
        raise HTTPException(401, "A valid session is required")

    app.dependency_overrides[get_current_session] = no_session
    with TestClient(app, base_url="https://localhost") as client:
        paths = [f"/api/v1/segments/{SEGMENT}/forecast",
                 f"/api/v1/meters/{uuid.uuid4()}/forecast", "/api/v1/stats/forecast"]
        for path in paths:
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["requestId"] == response.headers["X-Request-Id"]
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="VIEWER")
        for path in paths:
            assert client.get(path).status_code == 403
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="OPERATOR")
        for path in paths:
            for origin in ("invalid", "2026-01-01", "2099-01-01", "2026-11-14T01:00:00Z"):
                assert client.get(path, params={"origin": origin}).status_code == 422
        for path in ("/api/v1/segments/invalid/forecast", "/api/v1/meters/invalid/forecast"):
            assert client.get(path).status_code == 422
        for params in ({"size": 0}, {"page": -1}, {"regionId": "invalid"}):
            assert client.get("/api/v1/stats/forecast", params=params).status_code == 422
        assert client.get(paths[0], params={"includeMeters": "invalid"}).status_code == 422


@pytest.fixture
def catalog_forecast(golden_history):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.core.db import get_catalog_db, get_catalog_engine
    from app.models.geography import NetworkAsset, Region
    from app.models.clients import Client
    from app.models.files import File
    from app.models.metering import Meter, MeterReading

    app = create_app()
    with get_catalog_engine().connect() as connection:
        transaction = connection.begin()
        with Session(connection) as db:
            region = db.scalar(select(Region).where(Region.code == "DOBROGEA"))
            db.add(NetworkAsset(
                id=uuid.UUID(SEGMENT), code="SEG-013", name="Forecast test segment",
                region_id=region.id, type="LINE_SEGMENT", geometry="SRID=4326;POINT(28 44)",
            ))
            db.flush()
            meters = golden_history.meters
            for meter in meters.itertuples():
                client = Client(
                    id=uuid.uuid4(), region_id=region.id, external_code=f"forecast-{uuid.uuid4()}",
                    name_enc=b"test", email_enc=b"test", client_type=meter.client_type,
                )
                db.add(client)
                db.flush()
                db.add(Meter(
                    id=uuid.UUID(meter.id), external_code=meter.external_code,
                    asset_id=uuid.UUID(SEGMENT), client_id=client.id,
                ))
            db.flush()
            files, readings = [], []
            for d, day in enumerate(golden_history.slots):
                for m, slots in enumerate(day):
                    for k, energy in enumerate(slots):
                        file_id = uuid.uuid4()
                        start = (golden_history.start + pd.Timedelta(days=d, hours=k * 6)).to_pydatetime()
                        end = start + timedelta(hours=6)
                        files.append(dict(
                            id=file_id, region_id=region.id, category="METER_READING",
                            original_name="forecast-test", media_type="application/json",
                            size_bytes=1, sha256="0" * 64, storage_backend="db",
                            storage_locator=str(file_id), status="READY", created_at=start,
                        ))
                        readings.append(dict(
                            id=uuid.uuid4(), meter_id=uuid.UUID(meters.iloc[m].id),
                            reading_key=f"forecast:{d}:{k}", seq=d * 4 + k,
                            interval_start=start, interval_end=end, energy_kwh=float(energy),
                            file_id=file_id,
                            received_at=pd.Timestamp(
                                golden_history.arrival[d, m, k], tz="UTC"
                            ).to_pydatetime(),
                        ))
            db.execute(File.__table__.insert(), files)
            db.execute(MeterReading.__table__.insert(), readings)
            db.flush()
            app.dependency_overrides[get_catalog_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="OPERATOR")
            with TestClient(app, base_url="https://localhost") as client:
                yield client, app.state.forecast, db, region.id
        transaction.rollback()


@pytest.mark.integration
def test_catalog_sql_golden_cache_meter_and_pagination(catalog_forecast, monkeypatch):
    client, runtime, db, region = catalog_forecast
    path = f"/api/v1/segments/{SEGMENT}/forecast"
    response = client.get(path, params={"origin": "2026-11-14", "includeMeters": True})
    assert response.status_code == 200, response.text
    result = response.json()
    golden = json.loads((HANDOFF / "examples/segment-013-with-meters.json").read_text())
    for actual, expected in zip(result["forecasts"], golden["forecasts"]):
        assert {k: actual[k] for k in expected} == expected
    assert result["fallbackUsed"] is False
    meter_id = result["meters"][0]["meterId"]
    meter = client.get(f"/api/v1/meters/{meter_id}/forecast", params={"origin": "2026-11-14"}).json()
    assert meter["forecasts"] == result["meters"][0]["forecasts"]
    calls = []
    monkeypatch.setattr(runtime.service, "predict_segment", lambda *a, **k: calls.append(1))
    cached = client.get(path, params={"origin": "2026-11-14"}).json()
    assert cached["generatedAt"] == result["generatedAt"] and "meters" not in cached
    assert not calls
    for kind in ("segments", "meters"):
        assert client.get(f"/api/v1/{kind}/{uuid.uuid4()}/forecast").status_code == 404
    page = client.get("/api/v1/stats/forecast", params={
        "origin": "2026-11-14", "regionId": str(region), "size": 1, "page": 100,
    }).json()
    assert page["items"] == [] and page["totalElements"] > 0
    assert client.get("/api/v1/stats/forecast", params={"regionId": str(uuid.uuid4())}).json()["items"] == []
    runtime.service = None
    runtime.error = "Forecast model unavailable: checksum mismatch"
    unavailable = client.get(path, params={"origin": "2026-11-14"})
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "FORECAST_UNAVAILABLE"
    assert "checksum" in unavailable.json()["message"]
    assert unavailable.headers["Retry-After"] == "300"


@pytest.mark.integration
def test_sql_complete_slots_gaps_duplicates_overlap_and_cutoff(catalog_forecast):
    from sqlalchemy import select, text
    from app.forecast.service import READINGS
    from app.models.files import File
    from app.models.metering import MeterReading

    _, _, db, _ = catalog_forecast
    params = {
        "segment": SEGMENT, "start": ORIGIN.to_pydatetime() - timedelta(days=1),
        "end": ORIGIN.to_pydatetime(), "cutoff": (ORIGIN + pd.Timedelta(minutes=10)).to_pydatetime(),
    }
    initial = db.execute(text(READINGS), params).mappings().all()
    assert len(initial) == 28
    meter = initial[0]["meter_id"]
    reading = db.scalar(select(MeterReading).where(
        MeterReading.meter_id == uuid.UUID(meter), MeterReading.interval_start == params["start"],
    ))
    original = db.get(File, reading.file_id)
    reading.interval_end -= timedelta(hours=3)
    reading.energy_kwh /= 2
    file = File(
        id=uuid.uuid4(), region_id=original.region_id, category=original.category,
        original_name="half-slot", media_type="application/json", size_bytes=1,
        sha256="0" * 64, storage_backend="db", storage_locator="half-slot",
        status="READY", created_at=params["start"],
    )
    db.add(file)
    db.flush()
    half = MeterReading(
        meter_id=reading.meter_id, file_id=file.id, reading_key=str(uuid.uuid4()), seq=999999,
        interval_start=reading.interval_end, interval_end=reading.interval_end + timedelta(hours=3),
        energy_kwh=reading.energy_kwh, received_at=reading.received_at,
    )
    db.add(half)
    db.flush()
    assembled = db.execute(text(READINGS), params).mappings().all()
    assert len(assembled) == 28 and assembled[0]["energy_kwh"] == initial[0]["energy_kwh"]
    half.interval_start -= timedelta(minutes=15)
    db.flush()
    assert len(db.execute(text(READINGS), params).all()) == 27
    half.interval_start += timedelta(minutes=30)
    db.flush()
    assert len(db.execute(text(READINGS), params).all()) == 27
    half.interval_start = reading.interval_start
    db.flush()
    assert len(db.execute(text(READINGS), params).all()) == 27
    half.interval_start = reading.interval_end
    db.flush()
    # A missing interval and a late-arriving interval invalidate just their slots.
    db.execute(text("""UPDATE meter_readings SET received_at = :late
        WHERE meter_id = :meter AND interval_start = :start"""),
               {"late": ORIGIN.to_pydatetime() + timedelta(hours=1),
                "meter": meter, "start": params["start"]})
    assert len(db.execute(text(READINGS), params).all()) == 27
    # A shortened interval must not be extrapolated to a complete slot.
    db.execute(text("""UPDATE meter_readings SET interval_end = interval_end - INTERVAL '15 minutes'
        WHERE meter_id = :meter AND interval_start = :start"""),
               {"meter": meter, "start": params["start"] + timedelta(hours=6)})
    assert len(db.execute(text(READINGS), params).all()) == 26
