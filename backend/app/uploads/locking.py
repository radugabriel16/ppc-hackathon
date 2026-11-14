from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import anyio
from fastapi import HTTPException
from sqlalchemy import text

from app.core.db import get_catalog_engine


@asynccontextmanager
async def upload_lock(upload_id: UUID) -> AsyncIterator[None]:
    # Session-level locks span S3 calls without keeping a SQL transaction open.
    key = int.from_bytes(upload_id.bytes[:8], byteorder="big", signed=True)

    def acquire():
        connection = get_catalog_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            acquired = connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
            connection.commit()
            return connection, acquired
        except BaseException:
            connection.close()
            raise

    with anyio.CancelScope(shield=True):
        connection, acquired = await anyio.to_thread.run_sync(acquire)
    try:
        if not acquired:
            raise HTTPException(
                503, {"code": "UPLOAD_BUSY", "message": "Upload is being modified; retry shortly"},
                headers={"Retry-After": "1"},
            )
        yield
    finally:
        def release():
            try:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    connection.commit()
            except BaseException:
                connection.invalidate()
                raise
            finally:
                connection.close()

        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(release)
