from datetime import datetime
import logging
from typing import Literal
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser, MultiPartException

from app.auth.dependencies import get_current_user
from app.auth.security import LoginRateLimiter
from app.models.clients import Client, ConnectionCase, DocumentType
from app.models.geography import Region, Subregion
from app.models.enums import CaseStatus, ClientType, UserRole
from app.models.audit import AuditEvent
from app.core.api import ApiModel, Pagination, paginate
from app.core.db import get_catalog_db, get_catalog_engine
from app.document_intake import service
from app.document_intake.identity import (
    masked, valid_cnp, fingerprint, encrypt_customer_value,
    decrypt_customer_value, customer_name,
)
from app.models.auth import AppUser
from app.models.document_intake import DocumentIntakeBatch, DocumentIntakeItem
from app.models.files import File
from app.files.service import FileReader
from contextlib import aclosing
from app.uploads.locking import upload_lock

router = APIRouter(prefix='/api/v1', tags=['documents'])
logger = logging.getLogger(__name__)
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


class CustomerCreate(ApiModel):
    name: str = Field(repr=False, min_length=1, max_length=128)
    cnp: str = Field(repr=False, min_length=13, max_length=13)
    region_id: UUID | None = None
    segment_id: UUID | None = None

    @field_validator('name')
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Name is required')
        return value

    @field_validator('cnp')
    @classmethod
    def checked_cnp(cls, value: str) -> str:
        if not valid_cnp(value):
            raise ValueError('CNP validation failed')
        return value


def customer_operator(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role not in {UserRole.OPERATOR, UserRole.MANAGER}:
        service.error(403, 'FORBIDDEN', 'Insufficient permissions')
    return user


@router.get('/customers/{customer_id}/cnp')
def reveal_cnp(
    customer_id: UUID, response: Response,
    user: AppUser = Depends(customer_operator), db: Session = Depends(get_catalog_db),
):
    response.headers['Cache-Control'] = 'no-store'
    client = db.get(Client, customer_id)
    if client is None:
        service.error(404, 'CUSTOMER_NOT_FOUND', 'Customer not found')
    if client.cnp_enc is None:
        service.error(404, 'CNP_UNAVAILABLE', 'No recoverable CNP is available for this client')
    value = decrypt_customer_value(client.cnp_enc, client.id, field='cnp')
    db.add(AuditEvent(actor_id=user.id, action='CUSTOMER_CNP_REVEALED',
        entity_type='client', entity_id=client.id, occurred_at=service.now(), details={}))
    db.commit()
    return {'cnp': value}


@router.post('/customers', status_code=201)
def create_customer(
    body: CustomerCreate, response: Response,
    user: AppUser = Depends(customer_operator), db: Session = Depends(get_catalog_db),
):
    actor_id = user.id
    try:
        return _create_customer(body, response, user, db)
    except DBAPIError as exc:
        db.rollback()
        diagnostic = getattr(exc.orig, 'diag', None)
        sqlstate = getattr(exc.orig, 'sqlstate', None)
        logger.error(
            "Customer creation database failure actor_id=%s sqlstate=%s constraint=%s",
            actor_id, sqlstate, getattr(diagnostic, 'constraint_name', None),
        )
        unavailable = exc.connection_invalidated or (sqlstate or '').startswith('08')
        service.error(
            503 if unavailable else 500,
            'DATABASE_UNAVAILABLE' if unavailable else 'CUSTOMER_CREATE_FAILED',
            'Database is unavailable' if unavailable else 'Client creation failed',
        )


def _create_customer(body: CustomerCreate, response: Response, user: AppUser, db: Session):
    digest = fingerprint(body.cnp)
    if db.scalar(select(Client.id).where(Client.cnp_hmac == digest)) is not None:
        service.error(409, 'CUSTOMER_EXISTS', 'A client with this CNP already exists')
    region_id = body.region_id
    segment = db.get(Subregion, body.segment_id) if body.segment_id else None
    if body.segment_id and segment is None:
        service.error(422, 'INVALID_SCOPE', 'Selected segment does not exist')
    if segment is not None:
        if region_id is not None and region_id != segment.region_id:
            service.error(422, 'INVALID_SCOPE', 'Segment does not belong to the selected region')
        region_id = segment.region_id
    region = db.get(Region, region_id) if region_id else None
    if region is None:
        service.error(422, 'INVALID_SCOPE', 'Select a region or segment for this client')
    client_id = uuid4()
    location = (
        select(func.ST_PointOnSurface(Subregion.geometry)).where(Subregion.id == segment.id)
        if segment is not None else
        select(func.ST_PointOnSurface(Region.geometry)).where(Region.id == region.id)
    ).scalar_subquery()
    client = Client(
        id=client_id, region_id=region_id, external_code=f'CUSTOMER-{client_id.hex}',
        name_enc=encrypt_customer_value(body.name, client_id, field='name'),
        email_enc=encrypt_customer_value('', client_id, field='email'),
        client_type=ClientType.RESIDENTIAL, location=location,
        cnp_hmac=digest, cnp_masked=masked(body.cnp),
        cnp_enc=encrypt_customer_value(body.cnp, client_id, field='cnp'),
    )
    case = ConnectionCase(id=uuid4(), client_id=client_id,
        status=CaseStatus.OPEN, opened_at=service.now())
    db.add_all([client, case])
    db.add(AuditEvent(actor_id=user.id, action='CUSTOMER_CREATED',
        entity_type='client', entity_id=client_id, occurred_at=service.now(),
        details={'caseId': str(case.id), 'regionId': str(region_id)}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate_constraint = (
            getattr(exc.orig, 'sqlstate', None) == '23505'
            and getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None) == 'ix_clients_cnp_hmac'
        )
        if duplicate_constraint and db.scalar(
            select(Client.id).where(Client.cnp_hmac == digest)
        ) is not None:
            service.error(409, 'CUSTOMER_EXISTS', 'A client with this CNP already exists')
        raise
    response.headers['Cache-Control'] = 'no-store'
    types = db.scalars(select(DocumentType).where(
        DocumentType.required_for_connection.is_(True)
    ).order_by(DocumentType.code)).all()
    return {
        'id': client.id, 'name': body.name, 'cnpMasked': client.cnp_masked,
        'regionId': client.region_id, 'caseId': case.id,
        'documents': [dict(documentType=doc.code, name=doc.name,
            status='MISSING', fileId=None, uploadedAt=None) for doc in types],
    }


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
    db.commit()
    return {'customerId': client.id, 'customerName': customer_name(client), 'cnpMasked': client.cnp_masked}


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
