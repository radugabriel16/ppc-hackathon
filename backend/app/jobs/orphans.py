from datetime import timedelta
from uuid import UUID

import anyio
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine, get_storage_engine
from app.models.enums import FileCategory, StorageBackend
from app.models.files import File
from app.models.storage_db import FileContent
from app.policies.service import PolicyManager
from app.uploads.service import now

ORPHAN_GRACE = timedelta(minutes=10)
BATCH_SIZE = 1000


async def delete_orphan_contents(manager: PolicyManager) -> int:
    cutoff = now() - ORPHAN_GRACE
    cursor: UUID | None = None
    deleted = 0
    while True:
        def candidates():
            with Session(get_storage_engine()) as db:
                statement = select(FileContent.file_id).where(FileContent.created_at < cutoff)
                if cursor is not None:
                    statement = statement.where(FileContent.file_id > cursor)
                return list(db.scalars(statement.order_by(FileContent.file_id).limit(BATCH_SIZE)))

        ids = await anyio.to_thread.run_sync(candidates)
        if not ids:
            return deleted

        def referenced():
            with Session(get_catalog_engine()) as db:
                return set(db.scalars(select(File.id).where(File.id.in_(ids))))

        retained = await anyio.to_thread.run_sync(referenced)
        for file_id in ids:
            if file_id not in retained:
                async with manager.acquire(FileCategory.METER_READING):
                    await manager.storages[StorageBackend.db].delete(
                        FileCategory.METER_READING, str(file_id)
                    )
                deleted += 1
        cursor = ids[-1]
        if len(ids) < BATCH_SIZE:
            return deleted
