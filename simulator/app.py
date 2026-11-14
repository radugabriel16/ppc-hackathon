import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from engine import Engine
from store import iso


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    profile: Literal['normal', 'peak', 'storm'] | None = None
    readingsPerSecond: float | None = Field(default=None, gt=0)
    rate: float | None = Field(default=None, gt=0)
    intervalSeconds: float | None = Field(default=None, ge=5, le=300)


class Backfill(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    profile: Literal['normal', 'peak', 'storm'] | None = None
    from_: AwareDatetime | None = Field(default=None, alias='from')
    to: AwareDatetime | None = None
    anomalies: list[Literal['spike', 'zero', 'gap']] = Field(default_factory=list)


def create_app(engine=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine or Engine()
        await app.state.engine.open()
        try:
            yield
        finally:
            await app.state.engine.close()

    app = FastAPI(title='FileGrid Simulator', version='0.1.0', lifespan=lifespan)
    if engine is not None:
        app.state.engine = engine

    @app.get('/status')
    async def status():
        return app.state.engine.status()

    @app.post('/start')
    async def start(body: Start | None = None):
        body = body or Start()
        e = app.state.engine
        if sum(x is not None for x in (body.rate, body.readingsPerSecond, body.intervalSeconds)) > 1:
            raise HTTPException(422, 'Provide only one speed parameter')
        rate = body.readingsPerSecond or body.rate or len(e.meters) / (body.intervalSeconds or 5)
        if rate > min(e.max_rate, len(e.meters) / 5):
            raise HTTPException(422, 'Base rate exceeds safety limit (minimum 5 seconds per meter)')
        return e.start(body.profile or 'normal', rate)

    @app.post('/stop')
    async def stop():
        return app.state.engine.stop()

    @app.post('/backfill', status_code=202)
    async def backfill(body: Backfill | None = None):
        body = body or Backfill()
        e = app.state.engine
        if e.store.get('backfill'):
            raise HTTPException(409, 'A backfill is already active or paused')
        end = body.to or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        begin = body.from_ or end - timedelta(days=1)
        if begin >= end or end - begin > timedelta(days=31):
            raise HTTPException(422, 'Backfill must span more than zero and at most 31 days')
        if any(t.minute % 15 or t.second or t.microsecond for t in (begin, end)):
            raise HTTPException(422, 'Backfill boundaries must align to 15-minute intervals')
        run = e.new_run('backfill', body.profile or 'normal')
        e.store.set('backfill', {'runId': run['id'], 'cursor': iso(begin), 'to': iso(end),
            'profile': run['profile'], 'anomalies': body.anomalies, 'index': 0, 'meters': e.meters})
        return run

    @app.get('/runs')
    async def runs(page: int = 0, size: int = 20):
        if page < 0 or not 1 <= size <= 100:
            raise HTTPException(422, 'Invalid pagination')
        items = app.state.engine.store.runs()
        return dict(items=items[page * size:(page + 1) * size], page=page, size=size,
                    totalElements=len(items), totalPages=(len(items) + size - 1) // size)

    @app.get('/health/live')
    async def live():
        e = app.state.engine
        if e.tasks and any(t.done() for t in e.tasks):
            raise HTTPException(503, 'Simulator task stopped unexpectedly')
        e.store.db.execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/metrics')
    async def metrics():
        e = app.state.engine
        e.queue.set(e.store.count())
        return Response(generate_latest(e.registry), headers={'Content-Type': CONTENT_TYPE_LATEST})

    return app


logging.basicConfig(level=logging.INFO)
app = create_app()
