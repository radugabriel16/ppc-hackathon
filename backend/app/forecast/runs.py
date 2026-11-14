"""Persist scoped forecasts and atomically deduplicate operational exceedances."""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_role
from app.core.api import ApiModel
from app.core.db import get_catalog_db
from app.core.logging import get_request_id
from app.forecast.thresholds import threshold_for_run
from app.issues.router import resource
from app.models.alerts import Alert
from app.models.audit import AuditEvent
from app.models.enums import IssueSeverity, IssueStatus, IssueType, UserRole
from app.models.forecast import ForecastRun, SegmentThreshold
from app.models.geography import Region, Subregion
from app.models.issues import MapIssue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["stats"])


class RunCreate(ApiModel):
    scope: Literal["country", "region", "segment"]
    region_id: UUID | None = None
    segment_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "country" and (self.region_id or self.segment_id):
            raise ValueError("country scope does not accept regionId or segmentId")
        if self.scope == "region" and (not self.region_id or self.segment_id):
            raise ValueError("region scope requires only regionId")
        if self.scope == "segment" and not self.segment_id:
            raise ValueError("segment scope requires segmentId")
        return self


class ThresholdUpdate(ApiModel):
    daily_energy_kwh: float = Field(gt=0, allow_inf_nan=False)


def scoped_segments(db, body):
    statement = select(Subregion).order_by(Subregion.code)
    if body.region_id:
        if db.get(Region, body.region_id) is None:
            raise HTTPException(404, "Region not found")
        statement = statement.where(Subregion.region_id == body.region_id)
    if body.segment_id:
        segment = db.get(Subregion, body.segment_id)
        if segment is None:
            raise HTTPException(404, "Segment (subregion) not found")
        if body.region_id and segment.region_id != body.region_id:
            raise HTTPException(422, "segmentId does not belong to regionId")
        statement = statement.where(Subregion.id == body.segment_id)
    return db.scalars(statement).all()


def exceedance_issue(db, segment, point, threshold, actor_id, now):
    target = date.fromisoformat(point["date"])
    predicted = point["predictedEnergyKwh"]
    excess = round(predicted - threshold, 6)
    title = f"{segment.name} expected to exceed on {target} by {excess:.3f} kWh"
    description = (
        f"Expected consumption in {segment.name} on {target} (UTC): {predicted:.3f} kWh; "
        f"operational daily energy threshold {threshold:g} kWh exceeded by {excess:.3f} kWh "
        f"({100 * excess / threshold:.2f}%)."
        + (" Includes an explicitly flagged recent-daily-mean baseline." if point["fallbackUsed"] else "")
        + (" Includes an explicitly flagged intraday same-weekday bridge." if point.get("bridged") else "")
    )
    location, asset_id = db.execute(text("""
        SELECT ST_AsEWKT(ST_PointOnSurface(s.geometry)),
               (SELECT id FROM network_assets WHERE subregion_id=s.id ORDER BY code LIMIT 1)
        FROM subregions s WHERE s.id=:id
    """), {"id": segment.id}).one()
    if asset_id is None:
        raise HTTPException(503, "Forecast segment has no registered network asset")
    issue_id = db.scalar(insert(MapIssue).values(
        id=uuid4(), type=IssueType.ML_FORECAST, title=title, description=description,
        region_id=segment.region_id, subregion_id=segment.id, asset_id=asset_id,
        location=location, forecast_date=target, severity=IssueSeverity.HIGH,
        status=IssueStatus.OPEN, version=1, created_by=actor_id, created_at=now,
        is_historical=False,
    ).on_conflict_do_nothing().returning(MapIssue.id))
    if issue_id is None:
        return None
    db.add(Alert(
        severity="warning", message=title, occurred_at=now, received_at=now,
        payload={
            "status": "firing", "labels": {"alertname": "SegmentEnergyThresholdExceeded"},
            "annotations": {"summary": title, "description": description},
            "issueId": str(issue_id), "segmentId": str(segment.id),
            "targetDate": target.isoformat(), "predictedEnergyKwh": predicted,
            "thresholdKwh": threshold, "excessKwh": excess,
            "fallbackUsed": point["fallbackUsed"],
            "bridged": point.get("bridged", False),
        },
    ))
    return resource(db, db.get(MapIssue, issue_id)).model_dump(mode="json", by_alias=True)


def run_resource(run):
    return {
        "id": run.id, "scope": run.scope, "regionId": run.region_id,
        "segmentId": run.segment_id, "status": run.status,
        "createdAt": run.created_at, "completedAt": run.completed_at,
        "error": run.error, **(run.result or {"segments": [], "createdIssues": []}),
    }


@router.post("/forecast/runs", status_code=201)
def create_run(
    body: RunCreate, request: Request, user=Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    # A sync route executes all SQL/CPU inference in FastAPI's worker threadpool.
    segments = scoped_segments(db, body)
    run = ForecastRun(
        scope=body.scope, region_id=body.region_id, segment_id=body.segment_id,
        created_by=user.id, created_at=datetime.now(timezone.utc), status="RUNNING",
    )
    db.add(run)
    db.commit()
    run_id = run.id
    try:
        origin = datetime.now(timezone.utc).date() + timedelta(days=1)
        results, issues = [], []
        for segment in segments:
            config = threshold_for_run(db, segment.id, run.created_at)
            threshold = float(config.daily_energy_kwh)
            result = request.app.state.forecast.get_subregion(db, str(segment.id), origin)
            result = {
                **result, "regionId": str(segment.region_id), "thresholdKwh": threshold,
                "thresholdSource": config.source, "thresholdCalibration": config.calibration,
            }
            for point in result["forecasts"]:
                predicted = point["predictedEnergyKwh"]
                point["thresholdKwh"] = threshold
                point["excessKwh"] = round(max(0, predicted - threshold), 6) if predicted is not None else None
                if point["status"] == "READY" and predicted is not None and predicted > threshold:
                    issue = exceedance_issue(db, segment, point, threshold, user.id, run.created_at)
                    if issue:
                        issues.append(issue)
            results.append(result)
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        run.result = {"segments": results, "createdIssues": issues}
        db.commit()
    except (HTTPException, SQLAlchemyError, ValueError, RuntimeError) as exc:
        db.rollback()
        logger.exception("Forecast run failed run_id=%s", run_id)
        run = db.get(ForecastRun, run_id)
        run.status = "FAILED"
        run.error = "Forecast calculation failed; see server logs" if not isinstance(exc, HTTPException) else str(exc.detail)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            exc.status_code if isinstance(exc, HTTPException) else 503,
            {"code": "FORECAST_RUN_FAILED", "message": run.error},
            headers={"Location": f"/api/v1/forecast/runs/{run_id}"},
        ) from exc
    return run_resource(run)


@router.get("/forecast/runs/{id}", dependencies=[Depends(get_current_user)])
def get_run(id: UUID, db: Session = Depends(get_catalog_db)):
    run = db.get(ForecastRun, id)
    if run is None:
        raise HTTPException(404, "Forecast run not found")
    return run_resource(run)


@router.get("/forecast/thresholds", dependencies=[Depends(get_current_user)])
def thresholds(db: Session = Depends(get_catalog_db)):
    return [
        {"segmentId": config.segment_id, "regionId": segment.region_id,
         "dailyEnergyKwh": float(config.daily_energy_kwh),
         "source": config.source, "calibration": config.calibration}
        for config, segment in db.execute(
            select(SegmentThreshold, Subregion).join(Subregion).order_by(Subregion.code)
        )
    ]


@router.put("/forecast/thresholds/{segment_id}")
def update_threshold(
    segment_id: UUID, body: ThresholdUpdate, user=Depends(require_role(UserRole.MANAGER)),
    db: Session = Depends(get_catalog_db),
):
    config = db.get(SegmentThreshold, segment_id)
    if config is None:
        raise HTTPException(404, "Segment threshold not found")
    config.daily_energy_kwh = body.daily_energy_kwh
    config.source = "MANUAL"
    config.calibration = None
    db.add(AuditEvent(
        actor_id=user.id, action="SEGMENT_THRESHOLD_UPDATED", entity_type="subregion",
        entity_id=segment_id, occurred_at=datetime.now(timezone.utc),
        request_id=get_request_id(), details={"dailyEnergyKwh": body.daily_energy_kwh},
    ))
    db.commit()
    return {"segmentId": segment_id, "dailyEnergyKwh": float(config.daily_energy_kwh)}
