import logging
from datetime import datetime, timezone
from uuid import uuid4

import anyio
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.documents.checklists import MISSING_CASES
from app.jobs.scheduling import job_run
from app.models.enums import IssueStatus, IssueType
from app.models.issues import MapIssue

logger = logging.getLogger(__name__)


def sync_missing_documents(db, issue_id_for_case=None):
    now = datetime.now(timezone.utc)
    missing = db.execute(text(
        "SELECT * FROM (" + MISSING_CASES + ") missing WHERE case_status='OPEN'"
    )).mappings().all()
    missing_ids = [row["case_id"] for row in missing]
    for row in missing:
        asset = db.scalar(text("""
            SELECT id FROM network_assets WHERE subregion_id=:segment ORDER BY code LIMIT 1
        """), {"segment": row["segment_id"]})
        if asset is None:
            logger.warning("Cannot locate incomplete checklist case_id=%s", row["case_id"])
            continue
        title = f"Missing connection documents: client {row['external_code']}"
        description = "Required connection documents are missing: " + ", ".join(
            doc["name"] for doc in row["missing_document_types"]
        ) + "."
        issue_id = db.scalar(insert(MapIssue).values(
            id=issue_id_for_case(row["case_id"]) if issue_id_for_case else uuid4(),
            type=IssueType.MISSING_DOCUMENTS, title=title,
            description=description, region_id=row["region_id"],
            subregion_id=row["segment_id"], asset_id=asset, location=row["location"],
            client_id=row["client_id"], case_id=row["case_id"],
            severity="MEDIUM", status="OPEN", version=1, created_at=now,
            is_historical=False,
        ).on_conflict_do_nothing().returning(MapIssue.id))
        if issue_id is None:
            issue = db.scalar(select(MapIssue).where(
                MapIssue.case_id == row["case_id"], MapIssue.type == IssueType.MISSING_DOCUMENTS,
                MapIssue.is_historical.is_(False),
            ))
            if issue.description != description or issue.status == IssueStatus.RESOLVED:
                issue.description = description
                issue.status = IssueStatus.OPEN
                issue.resolved_at = None
                issue.version += 1
    for issue in db.scalars(select(MapIssue).where(
        MapIssue.type == IssueType.MISSING_DOCUMENTS, MapIssue.is_historical.is_(False),
        MapIssue.status != IssueStatus.RESOLVED, MapIssue.case_id.not_in(missing_ids),
    )):
        issue.status = IssueStatus.RESOLVED
        issue.resolved_at = now
        issue.version += 1
    db.flush()


async def missing_document_issues():
    async with job_run("missing_document_issues", 30) as run:
        if not run:
            return

        def sync():
            with Session(get_catalog_engine()) as db:
                sync_missing_documents(db)
                db.commit()

        await anyio.to_thread.run_sync(sync)
