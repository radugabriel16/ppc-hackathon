from datetime import datetime
from uuid import UUID

from app.core.api import ApiModel
from app.models.enums import CaseStatus, ClientType


class ClientResource(ApiModel):
    id: UUID
    region_id: UUID
    external_code: str
    client_type: ClientType


class CaseResource(ApiModel):
    id: UUID
    client_id: UUID
    status: CaseStatus
    opened_at: datetime
    due_at: datetime | None


class DocumentTypeResource(ApiModel):
    id: UUID
    code: str
    name: str
    required_for_connection: bool


class ClientDocumentResource(ApiModel):
    id: UUID
    case_id: UUID
    document_type_id: UUID
    file_id: UUID
    uploaded_at: datetime
