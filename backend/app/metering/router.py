import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_simulator_token
from app.core.api import Pagination, paginate
from app.core.db import get_catalog_db
from app.core.metrics import METER_INGEST_TOTAL
from app.metering.schemas import MeterReadingIngest, MeterReadingResource
from app.metering.service import ingest_reading
from app.models.enums import FileCategory
from app.models.metering import MeterReading

router = APIRouter(prefix="/api/v1", tags=["metering"])


@router.post(
    "/meter-readings/ingest", status_code=201, response_model=MeterReadingResource,
    dependencies=[Depends(require_simulator_token)],
)
async def ingest(
    request: Request, response: Response, db: Session = Depends(get_catalog_db),
):
    result = "error"
    try:
        manager = request.app.state.policy_manager
        async with manager.acquire(FileCategory.METER_READING) as policy:
            content = bytearray()
            digest = hashlib.sha256()
            async for chunk in request.stream():
                if len(content) + len(chunk) > policy.max_size_bytes:
                    raise HTTPException(413, "Reading exceeds the category size limit")
                content.extend(chunk)
                digest.update(chunk)
            raw = bytes(content)
            try:
                reading = MeterReadingIngest.model_validate_json(raw)
            except ValidationError as exc:
                raise RequestValidationError(exc.errors()) from exc
            resource, created = await ingest_reading(
                reading, raw, digest.hexdigest(), manager, db
            )
            response.status_code = 201 if created else 200
            result = "created" if created else "duplicate"
            return resource
    except HTTPException as exc:
        result = {409: "conflict", 503: "unavailable"}.get(exc.status_code, "invalid")
        raise
    except RequestValidationError:
        result = "invalid"
        raise
    finally:
        METER_INGEST_TOTAL.labels(result=result).inc()


@router.get("/meter-readings", dependencies=[Depends(get_current_user)])
def list_readings(
    meter_id: Annotated[UUID | None, Query(alias="meterId")] = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    if from_time is not None and to_time is not None and to_time < from_time:
        raise HTTPException(422, "'to' must not be before 'from'")
    statement = select(MeterReading)
    if meter_id is not None:
        statement = statement.where(MeterReading.meter_id == meter_id)
    if from_time is not None:
        statement = statement.where(MeterReading.interval_end >= from_time)
    if to_time is not None:
        statement = statement.where(MeterReading.interval_end <= to_time)
    return paginate(
        db, statement.order_by(MeterReading.interval_end.desc(), MeterReading.id),
        pagination, MeterReadingResource,
    )
