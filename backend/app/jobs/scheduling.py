from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

import anyio
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.models.maintenance import WorkerState
from app.uploads.locking import upload_lock
from app.uploads.service import now


@asynccontextmanager
async def job_run(name: str, interval_seconds: int = 0) -> AsyncIterator[bool]:
    # Reuse session advisory locks: no transaction is held across storage/SMTP I/O.
    entered = False
    try:
        async with upload_lock(uuid5(NAMESPACE_URL, f"filegrid:job:{name}")):
            entered = True

            def due():
                with Session(get_catalog_engine()) as db:
                    state = db.get(WorkerState, name)
                    return state is None or state.completed_at is None or (
                        state.completed_at <= now() - timedelta(seconds=interval_seconds)
                    )

            if not await anyio.to_thread.run_sync(due):
                yield False
                return
            yield True

            def completed():
                with Session(get_catalog_engine()) as db:
                    state = db.get(WorkerState, name)
                    if state is None:
                        state = WorkerState(name=name)
                        db.add(state)
                    state.completed_at = now()
                    db.commit()

            await anyio.to_thread.run_sync(completed)
    except HTTPException as exc:
        if entered or not isinstance(exc.detail, dict) or exc.detail.get("code") != "UPLOAD_BUSY":
            raise
        yield False
