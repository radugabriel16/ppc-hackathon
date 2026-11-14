from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.api import Pagination, paginate
from app.core.db import get_catalog_db
from app.documents.schemas import (
    CaseResource,
    ClientDocumentResource,
    ClientResource,
    DocumentTypeResource,
)
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType
from app.models.enums import FileStatus
from app.models.files import File

router = APIRouter(
    prefix="/api/v1", tags=["documents"], dependencies=[Depends(get_current_user)]
)


@router.get("/clients")
def list_clients(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(Client)
    if region_id is not None:
        statement = statement.where(Client.region_id == region_id)
    return paginate(db, statement.order_by(Client.id), pagination, ClientResource)


@router.get("/connection-cases")
def list_cases(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    statement = select(ConnectionCase).join(Client, ConnectionCase.client_id == Client.id)
    if region_id is not None:
        statement = statement.where(Client.region_id == region_id)
    return paginate(db, statement.order_by(ConnectionCase.id), pagination, CaseResource)


@router.get("/document-types", response_model=list[DocumentTypeResource])
def list_document_types(db: Session = Depends(get_catalog_db)):
    return db.scalars(select(DocumentType).order_by(DocumentType.code)).all()


@router.get("/connection-cases/{id}/documents")
def case_documents(id: UUID, db: Session = Depends(get_catalog_db)):
    if db.get(ConnectionCase, id) is None:
        raise HTTPException(404, "Connection case not found")
    rows = db.execute(
        select(ClientDocument, File.status)
        .join(File, ClientDocument.file_id == File.id)
        .where(ClientDocument.case_id == id)
        .order_by(ClientDocument.uploaded_at, ClientDocument.id)
    ).all()
    present = {doc.document_type_id for doc, status in rows if status == FileStatus.READY}
    required = db.scalars(
        select(DocumentType).where(DocumentType.required_for_connection.is_(True))
        .order_by(DocumentType.code)
    ).all()
    return {
        "caseId": id,
        "documents": [ClientDocumentResource.model_validate(doc) for doc, _ in rows],
        "missingDocumentTypes": [
            DocumentTypeResource.model_validate(doc) for doc in required if doc.id not in present
        ],
    }
