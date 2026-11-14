from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, TypeAdapter

from app.core.api import ApiModel
from app.models.enums import FileCategory, FileStatus, StorageBackend


class UploadMetadata(ApiModel):
    model_config = ConfigDict(extra="forbid")

    region_id: UUID | None = None


class ConnectionDocumentMetadata(UploadMetadata):
    category: Literal[FileCategory.CONNECTION_DOCUMENT]
    case_id: UUID
    document_type_id: UUID


class OutageRecordMetadata(UploadMetadata):
    category: Literal[FileCategory.OUTAGE_RECORD]
    asset_id: UUID
    started_at: AwareDatetime
    severity: str = Field(min_length=1, max_length=32)
    description: str | None = None


class DroneVideoMetadata(UploadMetadata):
    category: Literal[FileCategory.DRONE_VIDEO]
    asset_id: UUID
    recorded_at: AwareDatetime


FileUploadMetadata = Annotated[
    ConnectionDocumentMetadata | OutageRecordMetadata | DroneVideoMetadata,
    Field(discriminator="category"),
]
metadata_adapter = TypeAdapter(FileUploadMetadata)


class FileResource(ApiModel):
    id: UUID
    region_id: UUID
    category: FileCategory
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    storage_backend: StorageBackend
    fallback_used: bool
    status: FileStatus
    encrypted: bool
    created_at: datetime
    ready_at: datetime | None
    last_verified_at: datetime | None
