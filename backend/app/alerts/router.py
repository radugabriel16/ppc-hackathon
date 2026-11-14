from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.api import ApiModel
from app.core.db import get_catalog_db
from app.models.alerts import Alert

WEBHOOK_PATH = "/api/v1/alerts/webhook"
router = APIRouter(prefix="/api/v1/alerts", tags=["admin"])


class AlertmanagerAlert(ApiModel):
    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None


class AlertmanagerWebhook(ApiModel):
    version: Literal["4"]
    status: Literal["firing", "resolved"]
    receiver: str
    group_key: str
    group_labels: dict[str, str] = Field(default_factory=dict)
    common_labels: dict[str, str] = Field(default_factory=dict)
    common_annotations: dict[str, str] = Field(default_factory=dict)
    external_url: str | None = Field(default=None, alias="externalURL")
    truncated_alerts: int = Field(default=0, ge=0)
    alerts: list[AlertmanagerAlert] = Field(max_length=1000)


class AlertResource(ApiModel):
    id: UUID
    severity: str
    message: str
    occurred_at: datetime


@router.post("/webhook", status_code=204)
def receive_alerts(body: AlertmanagerWebhook, db: Session = Depends(get_catalog_db)) -> None:
    received = datetime.now(timezone.utc)
    for alert in body.alerts:
        severity = alert.labels.get("severity", "unknown")
        # Alertmanager's annotation convention is summary, then description.
        message = (
            alert.annotations.get("summary") or alert.annotations.get("description")
            or alert.labels.get("alertname") or "Alertmanager notification"
        )
        db.add(Alert(
            severity=severity, message=message, occurred_at=alert.starts_at,
            received_at=received, payload=alert.model_dump(mode="json", by_alias=True),
        ))
    db.commit()


@router.get(
    "/recent", response_model=list[AlertResource],
    dependencies=[Depends(get_current_user)],
)
def recent_alerts(db: Session = Depends(get_catalog_db)):
    return db.scalars(
        select(Alert).order_by(Alert.received_at.desc(), Alert.id.desc()).limit(100)
    ).all()
