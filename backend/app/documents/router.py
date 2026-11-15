from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import bindparam, exists, select, text
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
from app.models.enums import CaseStatus, IssueType
from app.models.files import File
from app.models.issues import MapIssue
from app.issues.service import validate_dates
from app.documents.checklists import MISSING_CASES
from app.document_intake.identity import customer_name
from app.stats.router import page_query

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
    segment_id: Annotated[UUID | None, Query(alias="segmentId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    client_id: Annotated[UUID | None, Query(alias="clientId")] = None,
    search: str | None = None, complete: bool | None = None,
    status: CaseStatus | None = None, type: IssueType | None = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    validate_dates(from_time, to_time)
    statement = select(ConnectionCase).join(Client, ConnectionCase.client_id == Client.id)
    if region_id is not None:
        statement = statement.where(Client.region_id == region_id)
    if search:
        statement = statement.where(Client.external_code.ilike('%' + search[:128] + '%'))
    missing_slot = exists(select(DocumentType.id).where(
        DocumentType.required_for_connection.is_(True),
        ~exists(select(ClientDocument.id).join(File).where(
            ClientDocument.case_id == ConnectionCase.id,
            ClientDocument.document_type_id == DocumentType.id,
            ClientDocument.superseded_at.is_(None), File.status == FileStatus.READY,
        )).correlate(ConnectionCase, DocumentType),
    ))
    if complete is not None:
        statement = statement.where(~missing_slot if complete else missing_slot)
    if client_id:
        statement = statement.where(ConnectionCase.client_id == client_id)
    if status:
        statement = statement.where(ConnectionCase.status == status)
    if from_time:
        statement = statement.where(ConnectionCase.opened_at >= from_time)
    if to_time:
        statement = statement.where(ConnectionCase.opened_at < to_time)
    for selected in (segment_id, subregion_id):
        if selected:
            statement = statement.where(text("""
                covered_subregion(coalesce(clients.location,
                    (SELECT location FROM meters WHERE client_id=clients.id
                     AND location IS NOT NULL AND ST_Covers(
                         (SELECT geometry FROM regions WHERE id=clients.region_id),location)
                     ORDER BY external_code LIMIT 1),
                    (SELECT ST_PointOnSurface(geometry) FROM regions WHERE id=clients.region_id)),
                    clients.region_id)=:segment
            """).bindparams(bindparam("segment", selected, unique=True)))
    if type:
        statement = statement.where(exists(select(MapIssue.id).where(
            MapIssue.case_id == ConnectionCase.id, MapIssue.type == type,
            MapIssue.is_historical.is_(False),
        )))
    result = paginate(db, statement.order_by(ConnectionCase.id), pagination, CaseResource)
    types = db.scalars(select(DocumentType).where(DocumentType.required_for_connection.is_(True)).order_by(DocumentType.code)).all()
    for row in result['items']:
        client = db.get(Client, row.client_id)
        row.customer_name, row.cnp_masked, row.region_id = customer_name(client), client.cnp_masked, client.region_id
        docs = db.execute(select(ClientDocument, File).join(File).where(
            ClientDocument.case_id == row.id, ClientDocument.superseded_at.is_(None),
            File.status == FileStatus.READY).order_by(ClientDocument.uploaded_at.desc())).all()
        row.document_slots = []
        for dtype in types:
            linked = next((doc for doc in docs if doc.ClientDocument.document_type_id == dtype.id), None)
            row.document_slots.append(dict(documentType=dtype.code, name=dtype.name,
                status='PRESENT' if linked else 'MISSING', fileId=linked.File.id if linked else None,
                uploadedAt=linked.ClientDocument.uploaded_at if linked else None))
        row.complete = all(d['status'] == 'PRESENT' for d in row.document_slots)
    return result


@router.get("/clients/missing-documents")
def missing_documents(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    segment_id: Annotated[UUID | None, Query(alias="segmentId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    status: CaseStatus | None = None,
    pagination: Pagination = Depends(), db: Session = Depends(get_catalog_db),
):
    return page_query(db, """
        WITH missing AS (""" + MISSING_CASES + """)
        SELECT client_id AS "clientId", external_code AS "externalCode",
               region_id AS "regionId", segment_id AS "segmentId",
               jsonb_agg(jsonb_build_object(
                   'caseId',case_id,'missingDocumentTypes',missing_document_types
               ) ORDER BY case_id) AS cases
        FROM missing
        WHERE (CAST(:region AS uuid) IS NULL OR region_id=:region)
          AND (CAST(:segment AS uuid) IS NULL OR segment_id=:segment)
          AND (CAST(:subregion AS uuid) IS NULL OR segment_id=:subregion)
          AND (CAST(:status AS text) IS NULL OR case_status::text=:status)
        GROUP BY client_id,external_code,region_id,segment_id ORDER BY external_code,client_id
    """, {
        "region": region_id, "segment": segment_id, "subregion": subregion_id,
        "status": status.value if status else None,
    }, pagination, "items")


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
        .where(ClientDocument.case_id == id, ClientDocument.superseded_at.is_(None))
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
