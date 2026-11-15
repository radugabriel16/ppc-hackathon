"""Store -> verify -> classify -> atomic link. No raw CNP or extracted text is persisted."""
from contextlib import aclosing
from datetime import datetime, timezone, timedelta
from tempfile import SpooledTemporaryFile

import anyio
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.metrics import INTAKE_TOTAL, INTAKE_REVIEW, INTAKE_DURATION
from app.document_intake.identity import fingerprint, masked, valid_cnp, encrypt_customer_value
from app.document_intake.parser import parse, media_type
from app.files.multipart import MultipartUpload
from app.files.schemas import UnassignedDocumentMetadata
from app.files.service import store_file, FileReader
from app.jobs.scheduling import job_run
from app.models.audit import AuditEvent
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType
from app.models.document_intake import DocumentIntakeBatch, DocumentIntakeItem
from app.models.enums import FileStatus, IssueType, IssueStatus
from app.models.files import File
from app.models.issues import MapIssue
from app.uploads.locking import upload_lock

PARSER_LIMIT = anyio.CapacityLimiter(2)
TYPES = {'ID', 'REQUEST_FORM', 'CONNECTION_APPROVAL'}


def now():
    return datetime.now(timezone.utc)


def error(status, code, message):
    raise HTTPException(status, {'code': code, 'message': message})


def audit(db, actor, action, item, **details):
    db.add(AuditEvent(actor_id=actor, action=action, entity_type='document_intake',
        entity_id=item.id, occurred_at=now(), details=details))


def review(item, reason):
    item.status = 'NEEDS_REVIEW'
    item.review_reason = reason
    item.review_queue = 'IDENTITY' if reason == 'IDENTITY_DOCUMENT' else 'MANUAL'


def batch_counts(db, batch_id):
    if batch_id is None:
        return
    batch = db.scalar(select(DocumentIntakeBatch).where(DocumentIntakeBatch.id == batch_id).with_for_update())
    rows = db.execute(select(DocumentIntakeItem.status, func.count()).where(
        DocumentIntakeItem.batch_id == batch_id).group_by(DocumentIntakeItem.status)).all()
    counts = dict(rows)
    batch.auto_linked_count = counts.get('AUTO_LINKED', 0)
    batch.review_count = sum(counts.get(status, 0) for status in ('NEEDS_REVIEW','CONFIRMED','REJECTED'))
    batch.failed_count = counts.get('FAILED', 0)
    if batch.sealed and not counts.get('PROCESSING'):
        batch.status = 'COMPLETED'
        batch.finished_at = batch.finished_at or now()


def customer(db, cnp):
    if not valid_cnp(cnp):
        error(422, 'CNP_INVALID', 'CNP validation failed')
    found = db.scalar(select(Client).where(Client.cnp_hmac == fingerprint(cnp)))
    if found is None:
        error(404, 'CUSTOMER_NOT_FOUND', 'No client matches this CNP')
    if found.cnp_enc is None:
        found.cnp_enc = encrypt_customer_value(cnp, found.id, field='cnp')
    return found


def close_complete_issue(db, case_id):
    required = db.scalars(select(DocumentType).where(
        DocumentType.required_for_connection.is_(True)
    ).order_by(DocumentType.code)).all()
    present = set(db.scalars(select(ClientDocument.document_type_id).join(File).where(
        ClientDocument.case_id == case_id, ClientDocument.superseded_at.is_(None), File.status == FileStatus.READY)))
    missing = [doc.name for doc in required if doc.id not in present]
    case = db.get(ConnectionCase, case_id)
    for issue in db.scalars(select(MapIssue).where(MapIssue.case_id == case_id,
        MapIssue.type == IssueType.MISSING_DOCUMENTS, MapIssue.is_historical.is_(False),
        MapIssue.status != IssueStatus.RESOLVED)):
        if not missing or case.status.value == 'CLOSED':
            issue.status, issue.resolved_at = IssueStatus.RESOLVED, now()
            issue.version += 1
        else:
            description = "Required connection documents are missing: " + ", ".join(missing) + "."
            if issue.description != description:
                issue.description = description
                issue.version += 1


def link(db, item, client, kind, actor, *, manual=False, replace=False):
    # Serialize every write to a client's checklist; two concurrent upload/review
    # requests cannot both populate a missing slot or replace the same version.
    db.scalar(select(Client.id).where(Client.id == client.id).with_for_update())
    cases = db.scalars(select(ConnectionCase).where(ConnectionCase.client_id == client.id)
        .order_by(ConnectionCase.opened_at.desc(), ConnectionCase.id).with_for_update()).all()
    opened = [case for case in cases if case.status.value == 'OPEN']
    candidates = opened or cases
    if len(candidates) != 1:
        review(item, 'CONTENT_MISMATCH')
        return
    case = candidates[0]
    dtype = db.scalar(select(DocumentType).where(DocumentType.code == kind))
    file = db.get(File, item.file_id)
    if not dtype or not file or file.status != FileStatus.READY or file.last_verified_at is None:
        error(409, 'FILE_NOT_READY', 'Verified storage is required before linking')
    current = db.execute(select(ClientDocument, File).join(File).where(
        ClientDocument.case_id == case.id, ClientDocument.document_type_id == dtype.id,
        ClientDocument.superseded_at.is_(None), File.status == FileStatus.READY)).all()
    identical = next((row for row in current if row.File.sha256 == file.sha256), None)
    if current and identical is None and not replace:
        review(item, 'TYPE_ALREADY_PRESENT')
        return
    if identical is None:
        for row in current:
            row.ClientDocument.superseded_at = now()
        file.region_id = client.region_id
        db.add(ClientDocument(case_id=case.id, document_type_id=dtype.id, file_id=file.id, uploaded_at=now()))
    else:
        item.file_id = identical.File.id
    previous_reason = item.review_reason
    item.status = 'CONFIRMED' if manual else 'AUTO_LINKED'
    item.customer_id, item.confirmed_type = client.id, kind
    item.review_queue, item.review_reason = None, None
    if manual:
        item.reviewed_by, item.reviewed_at = actor, now()
    audit(db, actor, 'DOCUMENT_REPLACED' if current and identical is None else 'DOCUMENT_LINKED', item,
          caseId=str(case.id), documentType=kind, manual=manual, idempotent=identical is not None,
          previousReviewReason=previous_reason, contentOverride=manual and previous_reason == 'CONTENT_MISMATCH',
          supersededFileIds=[str(row.File.id) for row in current] if identical is None else [])
    db.flush()
    close_complete_issue(db, case.id)


async def store_item(uploaded, manager, key, actor, batch_id=None, *, requested_customer=None, requested_type=None, confirm_manual=False):
    # Authenticated upload storage uses the same manager/encryption/compensation
    # pipeline as /files. Unknown clients are left unassigned, never guessed.
    with Session(get_catalog_engine(), expire_on_commit=False) as db:
        item = DocumentIntakeItem(batch_id=batch_id, original_file_name=(uploaded.filename or 'document')[:512],
            status='PROCESSING', requested_customer_id=requested_customer, requested_type=requested_type,
            confirm_manual=confirm_manual)
        db.add(item)
        db.commit()
        try:
            upload = MultipartUpload(manager.config)
            try:
                upload.filename = item.original_file_name
                upload.metadata = UnassignedDocumentMetadata()
                first = await uploaded.read(1024)
                upload.media_type = media_type(first)
                chunk = first
                while chunk:
                    upload.size += len(chunk)
                    if upload.size > 20 * 1024 * 1024:
                        error(413, 'PAYLOAD_TOO_LARGE', 'File exceeds 20 MiB')
                    upload.sha256.update(chunk)
                    await anyio.to_thread.run_sync(upload.stream.write, chunk)
                    chunk = await uploaded.read(65536)
                upload.stream.seek(0)
                result = await store_file(upload, manager, key, db, actor)
                item.file_id = result.id
                audit(db, actor, 'DOCUMENT_INTAKE_RECEIVED', item)
                db.commit()
            finally:
                upload.stream.close()
        except Exception:
            db.rollback()
            item = db.get(DocumentIntakeItem, item.id)
            item.status, item.error_detail = 'FAILED', 'STORAGE_FAILED'
            INTAKE_TOTAL.labels(source='batch' if batch_id else 'single', result='failed').inc()
            db.commit()
        return item.id


async def process_item(item_id, manager, key):
    async with upload_lock(item_id):
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            item = db.get(DocumentIntakeItem, item_id)
            if item is None or item.status != 'PROCESSING' or item.file_id is None:
                return
            file = db.get(File, item.file_id)
            actor = file.uploaded_by
            db.commit()
            with INTAKE_DURATION.time():
                try:
                    reader = FileReader(file, manager, key, actor, None)
                    with SpooledTemporaryFile(max_size=1024*1024) as buffer:
                        async with aclosing(reader.chunks()) as chunks:
                            async for chunk in chunks:
                                if buffer.tell() + len(chunk) > 20*1024*1024:
                                    raise ValueError('File size limit')
                                buffer.write(chunk)
                        buffer.seek(0)
                        data = buffer.read()
                    db.refresh(file)
                    parsed = await anyio.to_thread.run_sync(parse, data, limiter=PARSER_LIMIT)
                    item.detected_type = parsed.detected_type
                    candidate = None
                    if parsed.cnp:
                        item.extracted_cnp_hmac = fingerprint(parsed.cnp)
                        item.cnp_masked = masked(parsed.cnp)
                        candidate = db.scalar(select(Client).where(Client.cnp_hmac == item.extracted_cnp_hmac))
                        if candidate is not None and candidate.cnp_enc is None:
                            candidate.cnp_enc = encrypt_customer_value(parsed.cnp, candidate.id, field='cnp')
                        item.suggested_customer_id = candidate.id if candidate else None
                    reason = parsed.reason
                    if item.requested_customer_id or item.requested_type:
                        contradicts = ((parsed.detected_type is not None and parsed.detected_type != item.requested_type)
                            or (parsed.cnp is not None and (candidate is None or candidate.id != item.requested_customer_id)))
                        if contradicts:
                            review(item, 'CONTENT_MISMATCH')
                        elif parsed.detected_type == 'ID':
                            review(item, 'IDENTITY_DOCUMENT')
                        elif reason == 'NO_EXTRACTABLE_TEXT' and item.confirm_manual:
                            candidate = db.get(Client, item.requested_customer_id)
                            if candidate is None:
                                review(item, 'CUSTOMER_NOT_FOUND')
                            else:
                                link(db, item, candidate, item.requested_type, actor, manual=True)
                        elif reason:
                            review(item, reason)
                        elif candidate:
                            link(db, item, candidate, parsed.detected_type, actor)
                        else:
                            review(item, 'CUSTOMER_NOT_FOUND')
                    elif reason:
                        review(item, reason)
                    elif candidate is None:
                        review(item, 'CUSTOMER_NOT_FOUND')
                    else:
                        link(db, item, candidate, parsed.detected_type, actor)
                    item.version += 1
                    db.flush()
                    batch_counts(db, item.batch_id)
                    db.commit()
                except Exception:
                    db.rollback()
                    item = db.get(DocumentIntakeItem, item_id)
                    item.status, item.error_detail = 'FAILED', 'PROCESSING_FAILED'
                    item.version += 1
                    db.flush()
                    batch_counts(db, item.batch_id)
                    db.commit()
            result = {'AUTO_LINKED':'auto_linked','CONFIRMED':'auto_linked','NEEDS_REVIEW':'needs_review'}.get(item.status,'failed')
            INTAKE_TOTAL.labels(source='batch' if item.batch_id else 'single', result=result).inc()
            if item.review_reason:
                INTAKE_REVIEW.labels(reason=item.review_reason).inc()


async def run_intake(manager, key):
    async with job_run('document_intake') as run:
        if not run:
            return
        with Session(get_catalog_engine()) as db:
            ids = db.scalars(select(DocumentIntakeItem.id).where(DocumentIntakeItem.status == 'PROCESSING',
                DocumentIntakeItem.file_id.is_not(None)).order_by(DocumentIntakeItem.created_at).limit(25)).all()
        for item_id in ids:
            try:
                await process_item(item_id, manager, key)
            except HTTPException:
                # Another process may hold the advisory item lock. Retry next poll.
                continue
        with Session(get_catalog_engine()) as db:
            for batch in db.scalars(select(DocumentIntakeBatch).where(DocumentIntakeBatch.status == 'PROCESSING')):
                if batch.created_at < now() - timedelta(hours=1):
                    batch.sealed = True
                    for item in db.scalars(select(DocumentIntakeItem).where(
                        DocumentIntakeItem.batch_id == batch.id, DocumentIntakeItem.status == 'PROCESSING',
                        DocumentIntakeItem.file_id.is_(None))):
                        item.status, item.error_detail = 'FAILED', 'UPLOAD_INTERRUPTED'
                db.flush()
                batch_counts(db, batch.id)
            db.commit()
