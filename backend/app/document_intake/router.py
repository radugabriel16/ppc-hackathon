from datetime import datetime
from typing import Literal
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser, MultiPartException

from app.auth.dependencies import get_current_user
from app.auth.security import LoginRateLimiter
from app.models.clients import Client
from app.core.api import ApiModel, Pagination, paginate
from app.core.db import get_catalog_db, get_catalog_engine
from app.document_intake import service
from app.document_intake.identity import masked
from app.models.auth import AppUser
from app.models.document_intake import DocumentIntakeBatch, DocumentIntakeItem
from app.models.files import File
from app.files.service import FileReader
from contextlib import aclosing
from app.uploads.locking import upload_lock

router = APIRouter(prefix='/api/v1', tags=['documents'])
DocumentKind = Literal['ID', 'REQUEST_FORM', 'CONNECTION_APPROVAL']


class IntakeItem(ApiModel):
    id: UUID
    batch_id: UUID | None
    file_id: UUID | None
    original_file_name: str
    status: str
    review_queue: str | None
    review_reason: str | None
    detected_type: str | None
    cnp_masked: str | None
    suggested_customer_id: UUID | None
    confirmed_type: str | None
    customer_id: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    error_detail: str | None
    version: int
    created_at: datetime


class Confirm(ApiModel):
    document_type: DocumentKind
    cnp: str = Field(repr=False, min_length=13, max_length=13)
    version: int = Field(ge=1)
    replace_existing: bool = False


class Reject(ApiModel):
    reason: str = Field(min_length=1, max_length=500, repr=False)
    version: int = Field(ge=1)


async def multipart(request, batch=False):
    maximum = (200 if batch else 20)*1024*1024
    received = 0
    async def bounded():
        nonlocal received
        async for chunk in request.stream():
            received += len(chunk)
            if received > maximum + 1024*1024:
                raise MultiPartException('Upload body limit exceeded')
            yield chunk
    try:
        form = await MultiPartParser(request.headers, bounded(), max_files=50 if batch else 1, max_fields=5).parse()
    except MultiPartException as exc:
        raise HTTPException(413, 'Upload exceeds multipart limits') from exc
    files = [value for name, value in form.multi_items() if name == ('files' if batch else 'file') and isinstance(value, UploadFile)]
    if not files or any(isinstance(value, UploadFile) and value not in files for _, value in form.multi_items()):
        await form.close()
        service.error(422, 'VALIDATION_ERROR', 'Expected file or files multipart field')
    if sum(file.size or 0 for file in files) > maximum:
        await form.close()
        service.error(413, 'PAYLOAD_TOO_LARGE', 'Upload total size limit exceeded')
    return form, files


@router.post('/customer-documents', status_code=201, response_model=IntakeItem)
async def single(request: Request, user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db)):
    form, files = await multipart(request)
    try:
        client, kind = form.get('customerId'), form.get('documentType')
        if bool(client) != bool(kind) or (kind and kind not in service.TYPES):
            service.error(422, 'VALIDATION_ERROR', 'Customer and document type must be provided together')
        try:
            client_id = UUID(client) if client else None
        except ValueError:
            service.error(422, 'VALIDATION_ERROR', 'Invalid customer id')
        if client_id and db.get(Client, client_id) is None:
            service.error(404, 'CUSTOMER_NOT_FOUND', 'Selected client does not exist')
        actor = user.id
        db.commit()
        item_id = await service.store_item(files[0], request.app.state.policy_manager,
            request.app.state.document_key, actor, requested_customer=client_id,
            requested_type=kind, confirm_manual=str(form.get('confirmManual', '')).lower() == 'true')
        await service.process_item(item_id, request.app.state.policy_manager, request.app.state.document_key)
        with Session(get_catalog_engine()) as db:
            return IntakeItem.model_validate(db.get(DocumentIntakeItem, item_id))
    finally:
        await form.close()


@router.post('/customer-documents/batches', status_code=202)
async def batch(request: Request, user: AppUser = Depends(get_current_user), auth_db: Session = Depends(get_catalog_db)):
    actor = user.id
    auth_db.commit()
    form, files = await multipart(request, True)
    try:
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            batch = DocumentIntakeBatch(created_by=actor, total_count=len(files))
            db.add(batch)
            db.commit()
            batch_id = batch.id
        for file in files:
            await service.store_item(file, request.app.state.policy_manager, request.app.state.document_key,
                actor, batch_id)
        with Session(get_catalog_engine()) as db:
            batch = db.get(DocumentIntakeBatch, batch_id)
            batch.sealed = True
            service.batch_counts(db, batch_id)
            db.commit()
        return {'batchId': batch_id}
    finally:
        await form.close()


@router.get('/customer-documents/batches/{batch_id}')
def get_batch(batch_id: UUID, user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db)):
    batch = db.get(DocumentIntakeBatch, batch_id)
    if batch is None:
        service.error(404, 'NOT_FOUND', 'Batch not found')
    items = db.scalars(select(DocumentIntakeItem).where(DocumentIntakeItem.batch_id == batch_id)
        .order_by(DocumentIntakeItem.created_at, DocumentIntakeItem.id)).all()
    return dict(id=batch.id, status=batch.status, totalCount=batch.total_count,
        autoLinkedCount=batch.auto_linked_count, reviewCount=batch.review_count, failedCount=batch.failed_count,
        createdAt=batch.created_at, finishedAt=batch.finished_at, items=[IntakeItem.model_validate(i) for i in items])


@router.get('/customer-documents/review-items')
def review_items(queue: Literal['IDENTITY', 'MANUAL'] | None = None, batchId: UUID | None = None,
    pagination: Pagination = Depends(), user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db)):
    query = select(DocumentIntakeItem).where(DocumentIntakeItem.status == 'NEEDS_REVIEW')
    if queue:
        query = query.where(DocumentIntakeItem.review_queue == queue)
    if batchId:
        query = query.where(DocumentIntakeItem.batch_id == batchId)
    return paginate(db, query.order_by(DocumentIntakeItem.created_at, DocumentIntakeItem.id), pagination, IntakeItem)


# Bounded per-process, per-reviewer preview limiter. Raw CNPs never become keys.
_lookup_limiter = LoginRateLimiter(limit=30, window_seconds=60, max_keys=1024)


@router.get('/customers/lookup')
def lookup(cnp: str, user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db)):
    try:
        _lookup_limiter.check(str(user.id))
    except HTTPException as exc:
        raise HTTPException(429, {'code':'LOOKUP_RATE_LIMITED','message':'Too many customer lookups'}, headers=exc.headers) from None
    from app.models.audit import AuditEvent
    db.add(AuditEvent(actor_id=user.id, action='DOCUMENT_CUSTOMER_LOOKUP', entity_type='client',
        occurred_at=service.now(), details={}))
    db.commit()
    client = service.customer(db, cnp)
    return {'customerId': client.id, 'customerName': client.external_code, 'cnpMasked': client.cnp_masked}


async def review_action(item_id, body, request, user, confirming):
    async with upload_lock(item_id):
        with Session(get_catalog_engine(), expire_on_commit=False) as db:
            item = db.get(DocumentIntakeItem, item_id)
            if item is None:
                service.error(404, 'NOT_FOUND', 'Intake item not found')
            if item.version != body.version or item.status != 'NEEDS_REVIEW':
                service.error(409, 'VERSION_CONFLICT', 'Item changed; reload the review queue')
            if confirming:
                client = service.customer(db, body.cnp)
                file = db.get(File, item.file_id)
                db.commit()
                reader = FileReader(file, request.app.state.policy_manager, request.app.state.document_key, user.id, None)
                async with aclosing(reader.chunks()) as chunks:
                    async for _ in chunks:
                        pass
                db.refresh(file)
                service.link(db, item, client, body.document_type, user.id, manual=True, replace=body.replace_existing)
                item.cnp_masked = masked(body.cnp)
            else:
                item.status, item.review_queue = 'REJECTED', None
                item.reviewed_by, item.reviewed_at = user.id, service.now()
                # Free-form rejection reasons can contain PII; keep only the event,
                # never persist/log the input text in an unencrypted audit column.
                service.audit(db, user.id, 'DOCUMENT_REJECTED', item)
            item.version += 1
            db.flush()
            service.batch_counts(db, item.batch_id)
            db.commit()
            return IntakeItem.model_validate(item)


@router.post('/customer-documents/review-items/{item_id}/confirm', response_model=IntakeItem)
async def confirm(item_id: UUID, body: Confirm, request: Request, user: AppUser = Depends(get_current_user)):
    return await review_action(item_id, body, request, user, True)


@router.post('/customer-documents/review-items/{item_id}/reject', response_model=IntakeItem)
async def reject(item_id: UUID, body: Reject, request: Request, user: AppUser = Depends(get_current_user)):
    return await review_action(item_id, body, request, user, False)
