"""FastAPI entrypoint. One image, three roles selected by env ROLE (PHASE1.md section 2)."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.auth.middleware import csrf_origin_middleware
from app.admin.router import router as admin_router
from app.alerts.router import router as alerts_router
from app.auth.security import LoginRateLimiter, get_session_key, get_simulator_token
from app.core.db import get_catalog_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, set_request_id
from app.core.metrics import REQUEST_DURATION_SECONDS
from app.core.policy_schema import load_policies
from app.core.settings import get_settings
from app.core.tracing import configure_tracing
from app.documents.router import router as documents_router
from app.documents.encryption import DocumentKey
from app.files.router import router as files_router
from app.forecast.router import router as forecast_router
from app.forecast.runs import router as forecast_runs_router
from app.forecast.service import ForecastRuntime
from app.geography.router import router as geography_router
from app.issues.router import router as issues_router
from app.jobs.worker import run_worker_loop
from app.metering.router import router as metering_router
from app.policies.router import router as policies_router
from app.policies.service import PolicyManager
from app.storage.registry import create_storages
from app.stats.router import router as stats_router
from app.uploads.router import router as uploads_router
from app.auth.router import router as auth_router

logger = logging.getLogger("app.main")

# "files" mounts every domain router except metering, which is ingest-only.
FILES_ROLE_ROUTERS = (
    auth_router,
    geography_router,
    documents_router,
    files_router,
    uploads_router,
    issues_router,
    policies_router,
    admin_router,
    alerts_router,
    stats_router,
    forecast_router,
    forecast_runs_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Fail fast on a malformed policy file rather than at first request.
    app.state.policy_manager = PolicyManager(
        load_policies(settings.policies_path), create_storages(settings)
    )
    if settings.role in {"files", "ingest"}:
        get_session_key()
    if settings.role == "ingest":
        get_simulator_token()
    if settings.role in {"files", "worker"}:
        app.state.document_key = DocumentKey.load(settings)
    if settings.role == "files":
        from starlette.concurrency import run_in_threadpool

        app.state.forecast = await run_in_threadpool(ForecastRuntime)

    worker_task = None
    if settings.role == "worker":
        import asyncio

        worker_task = asyncio.create_task(run_worker_loop(
            app.state.policy_manager, app.state.document_key
        ))

    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="FileGrid API", version="0.1.0", lifespan=lifespan)
    configure_tracing(app, settings.role)
    register_exception_handlers(app)

    if settings.role == "ingest":
        app.include_router(metering_router)
    elif settings.role == "files":
        for r in FILES_ROLE_ROUTERS:
            app.include_router(r)
        app.state.login_rate_limiter = LoginRateLimiter()
        app.middleware("http")(csrf_origin_middleware)
    # ROLE=worker mounts no HTTP business routers; it only exposes health/metrics
    # below and runs the background loop started in `lifespan`.

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        set_request_id(request_id)
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start
        status_class = f"{response.status_code // 100}xx"
        REQUEST_DURATION_SECONDS.labels(
            route=getattr(request.scope.get("route"), "path", "unmatched"),
            method=request.method, status_class=status_class,
        ).observe(duration)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.get("/health/live", tags=["health"])
    async def health_live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def health_ready():
        try:
            engine = get_catalog_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("readiness check failed: %s", exc)
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    @app.get("/metrics", tags=["observability"])
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
