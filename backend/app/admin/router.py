import json
import logging
from datetime import datetime
from http.client import HTTPConnection, HTTPException as UpstreamHTTPException
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.core.api import ApiModel, Pagination, paginate
from app.core.db import get_catalog_db
from app.models.enums import UserRole
from app.models.jobs import ScenarioRun

logger = logging.getLogger("app.admin")
router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"],
    dependencies=[Depends(require_role(UserRole.MANAGER))],
)


class SimulatorStart(ApiModel):
    profile: str | None = None
    readings_per_second: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class SimulatorBackfill(ApiModel):
    profile: str | None = None
    from_: AwareDatetime | None = Field(default=None, alias="from")
    to: AwareDatetime | None = None


class ScenarioRunResource(ApiModel):
    id: UUID
    kind: str
    profile: str
    started_at: datetime
    ended_at: datetime | None
    counters: dict | None


def proxy_simulator(method: str, action: str, body: ApiModel | None = None) -> JSONResponse:
    connection = HTTPConnection("simulator", 8080, timeout=5)
    payload = json.dumps(body.model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )) if body is not None else None
    try:
        connection.request(
            method, f"/{action}", body=payload,
            headers={"Content-Type": "application/json"} if payload is not None else {},
        )
        response = connection.getresponse()
        content = response.read(1024 * 1024 + 1)
        status = response.status
    except (OSError, UpstreamHTTPException) as exc:
        logger.warning("Simulator request failed (%s)", type(exc).__name__)
        raise HTTPException(503, detail={
            "code": "SIMULATOR_UNAVAILABLE",
            "message": "Simulator is not running or is unreachable at http://simulator:8080",
        }, headers={"Retry-After": "5"}) from exc
    finally:
        connection.close()
    if len(content) > 1024 * 1024:
        raise HTTPException(502, detail="Simulator response exceeds 1 MiB")
    try:
        result = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(502, detail="Simulator returned an invalid JSON response") from exc
    return JSONResponse(status_code=status, content=result)


@router.get("/simulator/status")
def simulator_status():
    return proxy_simulator("GET", "status")


@router.post("/simulator/start")
def simulator_start(body: SimulatorStart | None = None):
    return proxy_simulator("POST", "start", body)


@router.post("/simulator/stop")
def simulator_stop():
    return proxy_simulator("POST", "stop")


@router.post("/simulator/backfill")
def simulator_backfill(body: SimulatorBackfill | None = None):
    return proxy_simulator("POST", "backfill", body)


@router.get("/scenario-runs")
def scenario_runs(
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    return paginate(
        db, select(ScenarioRun).order_by(ScenarioRun.started_at.desc(), ScenarioRun.id.desc()),
        pagination, ScenarioRunResource,
    )
