import pytest
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.policy_schema import load_policies
from app.core.settings import get_settings
from app.policies.service import PolicyManager
from app.storage.registry import create_storages


@pytest.fixture(scope="session", autouse=True)
def isolated_integration_stack(request):
    if not any(item.get_closest_marker("integration") for item in request.session.items):
        yield
        return
    from app.core import db as core
    from app.auth.seed import seed_users
    from app.history.migrate import migrate_history
    from app.storage.ftp import FtpStorage
    from app.storage.s3 import S3Storage
    from fixtures.seed import seed
    from fixtures.meters import seed_meters

    settings = get_settings()
    suffix = uuid4().hex
    original = (settings.catalog_db_name, settings.storage_db_name,
                settings.history_db_name, settings.s3_bucket)
    names = tuple(f"pytest_{kind}_{suffix}" for kind in ("catalog", "storage", "history"))
    admins = [core.get_catalog_engine(), core.get_storage_engine(),
              create_engine(settings.history_db_url("admin"))]
    patch = pytest.MonkeyPatch()
    created = []
    ftp_directory = f"pytest-{suffix}"
    ftp_admin = None
    s3 = None
    try:
        for admin, name in zip(admins, names):
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
                db.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created.append((admin, name))
        settings.catalog_db_name, settings.storage_db_name, settings.history_db_name = names
        settings.s3_bucket = f"pytest-{suffix}"
        for engine in (core.get_catalog_engine, core.get_storage_engine, core.get_history_engine):
            engine.cache_clear()
        core.CatalogSessionLocal = None
        patch.setenv("ALEMBIC_DATABASE_URL", settings.catalog_db_dsn)
        backend = Path(__file__).resolve().parents[1]
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "head")
        migrate_history()
        with core.get_storage_engine().begin() as db:
            db.exec_driver_sql((backend.parent / "infra/storage-db/init.sql").read_text())
        with Session(core.get_catalog_engine()) as db:
            seed(db)
            seed_meters(db)
            db.commit()
            seed_users(db)
        s3 = S3Storage(settings)
        s3.client.create_bucket(Bucket=settings.s3_bucket)
        if not all(item.get_closest_marker("ftp_down") for item in request.session.items):
            ftp_admin = FtpStorage(
                settings.ftp_host, settings.ftp_port, settings.ftp_user,
                settings.storage_secret("ftp_password"), settings.storage_io_timeout_seconds,
            )
            original_connection = FtpStorage._connection
            with original_connection(ftp_admin) as ftp:
                ftp.mkd(ftp_directory)

            @contextmanager
            def test_connection(adapter):
                with original_connection(adapter) as ftp:
                    ftp.cwd(ftp_directory)
                    yield ftp
            patch.setattr(FtpStorage, "_connection", test_connection)
        yield
    finally:
        if s3 is not None:
            for page in s3.client.get_paginator("list_objects_v2").paginate(Bucket=s3.bucket):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    s3.client.delete_objects(Bucket=s3.bucket, Delete={"Objects": objects})
            for upload in s3.client.list_multipart_uploads(Bucket=s3.bucket).get("Uploads", []):
                s3.client.abort_multipart_upload(
                    Bucket=s3.bucket, Key=upload["Key"], UploadId=upload["UploadId"],
                )
            s3.client.delete_bucket(Bucket=s3.bucket)
        if ftp_admin is not None:
            with original_connection(ftp_admin) as ftp:
                ftp.cwd(ftp_directory)
                for key in ftp.nlst():
                    UUID(key)
                    ftp.delete(key)
                ftp.cwd("/")
                ftp.rmd(ftp_directory)
        for engine in (core.get_catalog_engine, core.get_storage_engine, core.get_history_engine):
            if engine.cache_info().currsize:
                engine().dispose()
            engine.cache_clear()
        core.CatalogSessionLocal = None
        settings.catalog_db_name, settings.storage_db_name, settings.history_db_name, settings.s3_bucket = original
        patch.undo()
        for admin, name in reversed(created):
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
                db.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admins[-1].dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def policy_manager():
    settings = get_settings()
    return PolicyManager(
        load_policies(settings.policies_path), create_storages(settings)
    )
