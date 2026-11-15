"""Real PostgreSQL isolation: never split/reset the developer's operational catalog."""
import asyncio
import hashlib
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from history_common import verify_rows
from split_history import split_history
from seed_demo import seed_demo


def test_verification_rejects_missing_or_changed_rows():
    for destination in ([], [(1, {"value": 2})]):
        with pytest.raises(ValueError, match="NOT deleted"):
            verify_rows([(1, {"value": 1})], destination)
    verify_rows([(1, {"value": 1}), (2, {"value": 2})],
                [(2, {"value": 2}), (1, {"value": 1})])


@pytest.fixture
def isolated(monkeypatch):
    from app.core import db as core
    from app.core.settings import get_settings
    from fixtures.seed import seed
    from fixtures.meters import seed_meters
    from app.auth.seed import seed_users
    import history_common

    settings = get_settings()
    catalog_admin = core.get_catalog_engine()
    history_admin = create_engine(settings.history_db_url("admin"), isolation_level="AUTOCOMMIT")
    suffix = uuid4().hex
    catalog_name, history_name = f"split_catalog_{suffix}", f"split_history_{suffix}"
    storage_name = f"split_storage_{suffix}"
    storage_admin = core.get_storage_engine().execution_options(isolation_level="AUTOCOMMIT")
    engines = []
    try:
        for admin, names in ((catalog_admin, [catalog_name]), (history_admin, [history_name]),
                             (storage_admin, [storage_name])):
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                for name in names:
                    connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        catalog = create_engine(catalog_admin.url.set(database=catalog_name))
        history = create_engine(settings.history_db_url("writer").set(database=history_name))
        reader = create_engine(settings.history_db_url().set(database=history_name))
        storage = create_engine(storage_admin.url.set(database=storage_name))
        history_owner = create_engine(history_admin.url.set(database=history_name))
        engines.extend([catalog, history, reader, storage, history_owner])
        monkeypatch.setenv("ALEMBIC_DATABASE_URL", catalog.url.render_as_string(hide_password=False))
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        command.upgrade(config, "head")
        with history_owner.begin() as connection:
            connection.exec_driver_sql((Path(__file__).resolve().parents[1] /
                                       "app/history/migrations/0001_history.sql").read_text())
            connection.exec_driver_sql("""
                GRANT USAGE ON SCHEMA history TO filegrid_history_reader,filegrid_history_writer;
                GRANT SELECT ON ALL TABLES IN SCHEMA history TO filegrid_history_reader;
                GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA history TO filegrid_history_writer;
            """)
        with storage.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE file_contents(file_id uuid PRIMARY KEY,content bytea NOT NULL)")
        with Session(catalog) as db:
            seed(db)
            seed_meters(db)
            db.commit()
            seed_users(db)
        monkeypatch.setattr(core, "get_catalog_engine", lambda: catalog)
        monkeypatch.setattr(core, "get_storage_engine", lambda: storage)
        monkeypatch.setattr(core, "get_history_engine", lambda: reader)
        monkeypatch.setattr(history_common, "writer_engine", lambda: history)
        monkeypatch.setattr("split_history.writer_engine", lambda: history)
        for name, attribute, engine in (
            ("app.files.service", "get_catalog_engine", catalog),
            ("app.storage.telemetry", "get_catalog_engine", catalog),
            ("app.uploads.locking", "get_catalog_engine", catalog),
            ("app.jobs.scheduling", "get_catalog_engine", catalog),
            ("app.storage.registry", "get_storage_engine", storage),
            ("app.history.readings", "get_history_engine", reader),
        ):
            monkeypatch.setattr(importlib.import_module(name), attribute, lambda engine=engine: engine)
        original_identity = importlib.import_module("seed_demo").identity
        monkeypatch.setattr("seed_demo.identity", lambda value: original_identity(f"test:{suffix}:{value}"))
        yield SimpleNamespace(catalog=catalog, history=history, reader=reader, storage=storage)
    finally:
        for engine in engines:
            engine.dispose()
        for admin, names in ((catalog_admin, [catalog_name]), (history_admin, [history_name]),
                             (storage_admin, [storage_name])):
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                for name in names:
                    connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        history_admin.dispose()


def add_old_readings(d, count=5):
    with d.catalog.begin() as catalog, d.storage.begin() as storage:
        meter, region = catalog.execute(text("""
            SELECT m.id,a.region_id FROM meters m JOIN network_assets a ON a.id=m.asset_id
            ORDER BY m.id LIMIT 1
        """)).one()
        for index in range(count):
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)-timedelta(days=90+index)
            file_id, reading_id = uuid4(), uuid4()
            raw = f"history-{index}".encode()
            storage.execute(text("INSERT INTO file_contents VALUES (:id,:content)"),
                            {"id": file_id, "content": raw})
            catalog.execute(text("""
                INSERT INTO files(id,region_id,category,original_name,media_type,size_bytes,sha256,
                                  storage_backend,storage_locator,status,created_at)
                VALUES (:id,:region,'METER_READING','test-history','application/json',:size,:sha,
                        'db',CAST(:id AS text),'READY',:start)
            """), {"id": file_id, "region": region, "size": len(raw),
                   "sha": hashlib.sha256(raw).hexdigest(), "start": start})
            catalog.execute(text("""
                INSERT INTO meter_readings(id,meter_id,reading_key,seq,interval_start,interval_end,
                                           energy_kwh,file_id,received_at)
                VALUES (:id,:meter,:key,1,:start,:end,10,:file,:received)
            """), {"id": reading_id, "meter": meter, "key": str(reading_id), "start": start,
                   "end": start+timedelta(hours=6), "file": file_id,
                   "received": start+timedelta(hours=6, minutes=1)})


@pytest.mark.integration
def test_split_counts_restart_idempotency_and_reader_role(isolated, monkeypatch):
    d = isolated
    add_old_readings(d)
    import split_history as module
    original_remove = module.remove_unreferenced_files
    with d.catalog.connect() as db:
        reading_files = set(db.scalars(text("SELECT file_id FROM meter_readings")))
    def interrupted(db, ids):
        if reading_files.intersection(ids):
            raise RuntimeError("simulated interruption after archive commit")
        return original_remove(db, ids)
    with monkeypatch.context() as context:
        context.setattr(module, "remove_unreferenced_files", interrupted)
        with pytest.raises(RuntimeError, match="interruption"):
            split_history("a"*64, batch_size=2)
    with d.catalog.connect() as db, d.reader.connect() as history:
        assert db.scalar(text("SELECT count(*) FROM meter_readings")) == 5
        assert history.scalar(text("SELECT count(*) FROM history.meter_readings")) == 2
    first = split_history("a"*64, batch_size=2)
    assert first["moved"]["meter_readings"] == 5
    with d.catalog.connect() as db, d.reader.connect() as history:
        assert db.scalar(text("SELECT count(*) FROM meter_readings")) == 0
        assert history.scalar(text("SELECT count(*) FROM history.meter_readings")) == 5
        assert history.scalar(text("SELECT count(*) FROM history.file_contents")) == 5
        assert db.scalar(text("SELECT count(*) FROM map_issues WHERE is_historical")) == 0
    second = split_history("b"*64, batch_size=2)
    assert second["moved"]["meter_readings"] == 0
    assert second["filesDeleted"] == 0
    with d.reader.begin() as reader:
        with pytest.raises(SQLAlchemyError):
            reader.execute(text("DELETE FROM history.meter_readings"))
    # A live observation takes precedence over an archived reading with the same key.
    from app.history.readings import complete_readings
    with d.history.connect() as history, Session(d.catalog) as db:
        row = dict(history.execute(text("SELECT * FROM history.meter_readings LIMIT 1")).mappings().one())
        region, asset = db.execute(text("""
            SELECT a.region_id,a.id FROM meters m JOIN network_assets a ON a.id=m.asset_id WHERE m.id=:id
        """), {"id": row["meter_id"]}).one()
        file_id = uuid4()
        db.execute(text("""
            INSERT INTO files(id,region_id,category,original_name,media_type,size_bytes,sha256,
                              storage_backend,storage_locator,status,created_at)
            VALUES (:id,:region,'METER_READING','live','application/json',1,:sha,'db','live','READY',now())
        """), {"id": file_id, "region": region, "sha": "0"*64})
        db.execute(text("""
            INSERT INTO meter_readings(id,meter_id,reading_key,seq,interval_start,interval_end,
                                       energy_kwh,file_id,received_at)
            VALUES (:id,:meter_id,:reading_key,:seq,:interval_start,:interval_end,20,:file_id,:received_at)
        """), {**row, "id": uuid4(), "file_id": file_id})
        points = complete_readings(db, asset, row["interval_start"], row["interval_end"],
                                   datetime.now(timezone.utc))
        assert len(points) == 1 and points[0]["energy_kwh"] == 20
        db.rollback()


@pytest.mark.integration
def test_bad_payload_never_deletes_catalog(isolated):
    d = isolated
    add_old_readings(d, 1)
    with d.storage.begin() as storage:
        storage.execute(text("UPDATE file_contents SET content='tampered'::bytea"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        split_history("a"*64, batch_size=1)
    with d.catalog.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM meter_readings")) == 1


@pytest.mark.integration
def test_demo_twice_reset_and_history_up_down(isolated, monkeypatch):
    from app.auth.dependencies import get_current_user
    from app.core.db import get_catalog_db
    from app.main import create_app
    from app.models.auth import AppUser
    from sqlalchemy import select
    d = isolated
    split_history("a"*64, batch_size=2)
    first = asyncio.run(seed_demo(reset=True))
    second = asyncio.run(seed_demo())
    assert first["counts"] == second["counts"]
    assert second["filesCreated"] == second["readingsInserted"] == 0
    assert first["counts"]["meters"] == 144
    assert first["counts"]["connection_cases"] == 30
    assert first["historicalIssues"] == 0
    with Session(d.catalog) as db:
        assert db.scalar(text("""
            SELECT count(*) FROM files WHERE category<>'METER_READING'
        """)) == 81
        assert db.scalar(text("""
            SELECT count(*) FROM files WHERE category='CONNECTION_DOCUMENT' AND encrypted
                AND storage_backend='s3' AND length(sha256)=64
        """)) == 75
        assert db.scalar(text("""
            SELECT bool_and(ST_Covers(s.geometry,i.location))
            FROM map_issues i JOIN subregions s ON s.id=i.subregion_id
        """))
        assert set(db.scalars(text("SELECT DISTINCT type::text FROM map_issues"))) == {
            "OUTAGE_REPORT", "OUTAGE_VIDEO", "DRONE_DETECTED", "MISSING_DOCUMENTS", "ML_FORECAST",
        }
        app = create_app()
        app.dependency_overrides[get_catalog_db] = lambda: db
        user = db.scalar(select(AppUser).where(AppUser.username == "operator"))
        app.dependency_overrides[get_current_user] = lambda: user
        asset = db.scalar(text("SELECT asset_id FROM meters LIMIT 1"))
        with TestClient(app, base_url="https://localhost") as client:
            path = f"/api/v1/segments/{asset}/forecast"
            result = client.get(path)
            assert result.status_code == 200, result.text
            assert result.json()["method"] == "hgb_smooth"
            assert not result.json()["fallbackUsed"]
            assert client.get("/api/v1/map/features?layer=ISSUES&size=2").json()["hasMore"]
            assert client.get("/api/v1/map/features?layer=ISSUES&bbox=2,48,3,49").json()["features"] == []
            assert client.get("/api/v1/map/features?layer=ISSUES&bbox=nan,1,2,3").status_code == 422
            broken = create_engine(d.reader.url.set(port=1), connect_args={"connect_timeout": 1})
            monkeypatch.setattr("app.history.readings.get_history_engine", lambda: broken)
            down = client.get(path)
            assert down.status_code == 503 and down.json()["code"] == "HISTORY_UNAVAILABLE"
            assert client.get("/api/v1/files").status_code == 200
            assert client.get("/api/v1/meters").status_code == 200
            assert client.get("/api/v1/map/features?layer=ISSUES").status_code == 200
            broken.dispose()
        db.rollback()
    monkeypatch.setattr("app.history.readings.get_history_engine", lambda: d.reader)
    reset = asyncio.run(seed_demo(reset=True))
    assert reset["counts"] == first["counts"]
