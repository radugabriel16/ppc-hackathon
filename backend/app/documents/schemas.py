from datetime import datetime
from uuid import UUID

from pydantic import Field
from app.core.api import ApiModel
from app.models.enums import CaseStatus, ClientType


class ClientResource(ApiModel):
    id: UUID
    region_id: UUID
    external_code: str
    client_type: ClientType


class CaseResource(ApiModel):
    customer_name: str | None = None
    cnp_masked: str | None = None
    region_id: UUID | None = None
    complete: bool = False
    document_slots: list[dict] = Field(default_factory=list, serialization_alias="documents")
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
