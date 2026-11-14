import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import anyio
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.jobs.scheduling import job_run
from app.models.clients import ClientDocument, ConnectionCase, DocumentType
from app.models.enums import CaseStatus, FileStatus, IssueStatus
from app.models.files import File
from app.models.issues import MapIssue
from app.models.maintenance import ReminderDelivery
from app.uploads.service import now

logger = logging.getLogger("app.jobs.reminders")


def period_start(at: datetime) -> datetime:
    seconds = get_settings().reminder_period_hours * 3600
    return datetime.fromtimestamp(int(at.timestamp()) // seconds * seconds, timezone.utc)


def reminder_candidates():
    settings = get_settings()
    period = period_start(now())
    with Session(get_catalog_engine()) as db:
        def unsent(kind, entity):
            return ~exists().where(
                ReminderDelivery.kind == kind, ReminderDelivery.entity_id == entity,
                ReminderDelivery.period_start == period,
            )

        issues = db.scalars(select(MapIssue.id).where(
            MapIssue.is_historical.is_(False),
            MapIssue.status != IssueStatus.RESOLVED,
            MapIssue.created_at <= now() - timedelta(hours=settings.reminder_after_hours),
            unsent("issue", MapIssue.id),
        ).order_by(MapIssue.created_at, MapIssue.id).limit(settings.worker_batch_size)).all()
        present = exists(select(ClientDocument.id).join(
            File, File.id == ClientDocument.file_id
        ).where(
            ClientDocument.case_id == ConnectionCase.id,
            ClientDocument.document_type_id == DocumentType.id,
            File.status == FileStatus.READY,
        ).correlate(ConnectionCase, DocumentType))
        missing = exists(select(DocumentType.id).where(
            DocumentType.required_for_connection.is_(True), ~present,
        ).correlate(ConnectionCase))
        cases = db.scalars(select(ConnectionCase.id).where(
            ConnectionCase.status == CaseStatus.OPEN, missing,
            unsent("checklist", ConnectionCase.id),
        ).order_by(ConnectionCase.opened_at, ConnectionCase.id)
            .limit(settings.worker_batch_size - len(issues))).all()
    return [(kind, entity_id, period) for kind, ids in (
        ("issue", issues), ("checklist", cases),
    ) for entity_id in ids]


def send_reminder(kind, entity_id, period) -> None:
    settings = get_settings()
    with Session(get_catalog_engine()) as db:
        delivery_key = (kind, entity_id, period)
        if db.get(ReminderDelivery, delivery_key) is not None:
            return
        db.add(ReminderDelivery(
            kind=kind, entity_id=entity_id, period_start=period,
            attempted_at=now(), status="ATTEMPTED",
        ))
        db.commit()
    # Reserve before SMTP: a crash/ambiguous SMTP ACK must not duplicate mail.
    message = EmailMessage()
    message["From"] = settings.reminder_from
    message["To"] = settings.reminder_to
    message["Subject"] = f"FileGrid: {'unresolved issue' if kind == 'issue' else 'incomplete document checklist'}"
    message["Message-ID"] = f"<{kind}.{entity_id}.{int(period.timestamp())}@filegrid.local>"
    message.set_content(f"Review {kind} {entity_id}. No client data is included in this reminder.")
    status = "SENT"
    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
        ) as smtp:
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        status = "FAILED"
        logger.exception("Reminder delivery failed kind=%s entity_id=%s", kind, entity_id)
        raise
    finally:
        with Session(get_catalog_engine()) as db:
            db.get(ReminderDelivery, delivery_key).status = status
            db.commit()


async def send_reminders() -> None:
    async with job_run("reminders", 5) as run:
        if not run:
            return
        for kind, entity_id, period in await anyio.to_thread.run_sync(reminder_candidates):
            try:
                await anyio.to_thread.run_sync(send_reminder, kind, entity_id, period)
            except (OSError, smtplib.SMTPException):
                # Already logged and durably recorded; independent reminders can continue.
                continue
