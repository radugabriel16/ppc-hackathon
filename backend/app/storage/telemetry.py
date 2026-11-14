"""Persist observations independently of catalog domain transactions."""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.models.jobs import StorageOperation

logger = logging.getLogger("app.storage.telemetry")


def record_operation(category, storage, operation, size, duration_ms, outcome):
    try:
        with Session(get_catalog_engine()) as db:
            db.add(StorageOperation(
                category=category, storage=storage, operation=operation,
                bytes=size, duration_ms=duration_ms, outcome=outcome,
                occurred_at=datetime.now(timezone.utc),
            ))
            db.commit()
    except SQLAlchemyError:
        # Telemetry failure must not turn a completed storage write into a retry.
        logger.exception("Could not persist storage operation telemetry")
