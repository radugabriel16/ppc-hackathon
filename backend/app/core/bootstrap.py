"""Serialize migrations and seed an empty catalog without resetting existing data."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.seed import seed_users
from app.core.db import get_catalog_engine, get_storage_engine
from app.models import Region
from app.history.migrate import migrate_history
from fixtures.seed import seed
from fixtures.geography import seed_geography
from fixtures.meters import seed_meters
from fixtures.document_clients import seed_document_clients

BOOTSTRAP_LOCK_ID = 7346021901


def main() -> None:
    engine = get_catalog_engine()
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    with engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:id)"), {"id": BOOTSTRAP_LOCK_ID})
        try:
            command.upgrade(config, "head")
            migrate_history()
            with get_storage_engine().begin() as storage:
                storage.exec_driver_sql(
                    (backend_dir.parent / "infra/storage-db/init.sql").read_text()
                )
            with Session(engine) as session:
                if session.scalar(select(Region.id).limit(1)) is None:
                    seed(session)
                    print("Catalog seed complete.")
                else:
                    print("Catalog already populated; seed skipped.")
                seed_geography(session)
                seed_meters(session)
                seed_document_clients(session)
                session.commit()
                seed_users(session)
                print("Demo accounts ready (existing credentials preserved).")
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": BOOTSTRAP_LOCK_ID})


if __name__ == "__main__":
    main()
