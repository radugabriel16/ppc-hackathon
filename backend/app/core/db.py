"""SQLAlchemy engines/sessions for catalog-db and storage-db (two separate Postgres instances)."""
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings


@lru_cache
def get_catalog_engine():
    settings = get_settings()
    return create_engine(settings.catalog_db_dsn, pool_pre_ping=True)


@lru_cache
def get_storage_engine():
    settings = get_settings()
    return create_engine(settings.storage_db_dsn, pool_pre_ping=True)


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
