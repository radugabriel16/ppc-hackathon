import logging
from datetime import timedelta
from uuid import UUID

import anyio
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.jobs.scheduling import job_run
from app.models.enums import FileCategory, FileStatus, StorageBackend
from app.models.files import File
from app.models.maintenance import WorkerState
from app.policies.service import PolicyManager
from app.storage.base import StorageUnavailable
from app.uploads.service import now

logger = logging.getLogger("app.jobs.orphans")
ORPHAN_GRACE = timedelta(minutes=10)
BATCH_SIZE = 1000


async def delete_orphan_contents(manager: PolicyManager) -> int:
    async with job_run("orphan_contents") as run:
        if not run:
            return 0
        deleted = 0
        for backend, category in (
            (StorageBackend.db, FileCategory.METER_READING),
            (StorageBackend.ftp, FileCategory.OUTAGE_RECORD),
            (StorageBackend.s3, FileCategory.DRONE_VIDEO),
        ):
            try:
                deleted += await delete_backend_orphans(manager, backend, category)
            except StorageUnavailable:
                logger.exception("Orphan inventory deferred storage=%s", backend.value)
        return deleted


async def delete_backend_orphans(
    manager: PolicyManager, backend: StorageBackend, category: FileCategory,
) -> int:
    state_name = "orphan_cursor" if backend == StorageBackend.db else f"orphan_cursor_{backend.value}"
    cutoff = now() - ORPHAN_GRACE

    def load_cursor():
        with Session(get_catalog_engine()) as db:
            state = db.get(WorkerState, state_name)
            return state.cursor if state is not None else None

    cursor = await anyio.to_thread.run_sync(load_cursor)
    batch_size = min(BATCH_SIZE, get_settings().worker_batch_size)
    storage = manager.storages[backend]
    async with manager.acquire(category):
        page = await storage.inventory(category, cursor, batch_size)
        ids = [UUID(item.key) for item in page.objects if item.modified_at < cutoff]

        def referenced():
            with Session(get_catalog_engine()) as db:
                return set(db.scalars(select(File.id).where(
                    File.id.in_(ids),
                    or_(
                        File.storage_backend == backend,
                        File.status == FileStatus.STAGING,
                    ),
                )))

        retained = await anyio.to_thread.run_sync(referenced)
        deleted = 0
        for file_id in ids:
            if file_id not in retained:
                await storage.delete(category, str(file_id))
                deleted += 1

    def save_cursor():
        with Session(get_catalog_engine()) as db:
            state = db.get(WorkerState, state_name)
            if state is None:
                state = WorkerState(name=state_name)
                db.add(state)
            state.cursor = page.next_cursor
            db.commit()
    await anyio.to_thread.run_sync(save_cursor)
    return deleted
