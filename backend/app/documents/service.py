from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.files.schemas import ConnectionDocumentMetadata
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType
from app.models.files import File


def document_region(db: Session, metadata: ConnectionDocumentMetadata) -> UUID:
    region_id = db.scalar(
        select(Client.region_id)
        .join(ConnectionCase, ConnectionCase.client_id == Client.id)
        .where(ConnectionCase.id == metadata.case_id)
        .with_for_update(of=(Client, ConnectionCase))
    )
    if region_id is None:
        raise HTTPException(404, "Connection case not found")
    if db.get(DocumentType, metadata.document_type_id) is None:
        raise HTTPException(404, "Document type not found")
    return region_id


def link_document(db: Session, file: File, metadata: ConnectionDocumentMetadata) -> None:
    db.add(
        ClientDocument(
            case_id=metadata.case_id,
            document_type_id=metadata.document_type_id,
            file_id=file.id,
            uploaded_at=file.ready_at,
        )
    )
