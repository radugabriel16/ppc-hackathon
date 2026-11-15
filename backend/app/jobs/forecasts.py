import anyio
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.forecast.service import ForecastRuntime
from app.forecast.snapshots import refresh_snapshots
from app.jobs.scheduling import job_run

_runtime = None


async def daily_forecasts():
    async with job_run("daily_forecasts", 60) as run:
        if not run:
            return
        def calculate():
            global _runtime
            if _runtime is None:
                _runtime = ForecastRuntime()
            with Session(get_catalog_engine()) as db:
                refresh_snapshots(db, _runtime)
        await anyio.to_thread.run_sync(calculate)
