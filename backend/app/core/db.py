"""SQLAlchemy engines/sessions for catalog-db and storage-db (two separate Postgres instances)."""
from collections.abc import Generator
from functools import lru_cache

import sqlalchemy
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings


@lru_cache
def get_catalog_engine():
    settings = get_settings()
    return sqlalchemy.create_engine(settings.catalog_db_dsn, pool_pre_ping=True)


@lru_cache
def get_history_engine() -> Engine:
    return sqlalchemy.create_engine(
        get_settings().history_db_url(), pool_pre_ping=True,
        pool_size=4, max_overflow=0, pool_timeout=2,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=10000"},
    )


@lru_cache
def get_storage_engine() -> Engine:
    settings = get_settings()
    timeout = max(1, int(settings.storage_io_timeout_seconds))
    return sqlalchemy.create_engine(
        settings.storage_db_dsn,
        pool_pre_ping=True,
        pool_size=settings.storage_max_concurrency,
        max_overflow=0,
        pool_timeout=settings.storage_io_timeout_seconds,
        connect_args={
            "connect_timeout": timeout,
            "options": f"-c statement_timeout={int(settings.storage_io_timeout_seconds * 1000)}",
        },
    )


CatalogSessionLocal = None


def _catalog_sessionmaker() -> sessionmaker:
    global CatalogSessionLocal
    if CatalogSessionLocal is None:
        CatalogSessionLocal = sessionmaker(
            bind=get_catalog_engine(), autoflush=False, autocommit=False, expire_on_commit=False
        )
    return CatalogSessionLocal


def get_catalog_db() -> Generator[Session, None, None]:
    session = _catalog_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
