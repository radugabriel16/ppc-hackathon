"""Core `files` catalog table: one row per stored file, regardless of category."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, BigInteger, Boolean, Enum, ForeignKey, Integer, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin
from app.models.enums import FileCategory, FileStatus, StorageBackend


class File(UUIDPkMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("region_id IS NOT NULL OR category = 'CONNECTION_DOCUMENT'", name="ck_unassigned_connection_document"),
        UniqueConstraint("placed_issue_id", name="uq_files_placed_issue"),
    )

    subregion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subregions.id", ondelete="SET NULL"), index=True,
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    category: Mapped[FileCategory] = mapped_column(
        Enum(FileCategory, name="file_category"), nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[StorageBackend] = mapped_column(
        Enum(StorageBackend, name="storage_backend"), nullable=False
    )
    storage_locator: Mapped[str] = mapped_column(String(1024), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="file_status"), nullable=False, default=FileStatus.STAGING, index=True
    )
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encryption_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ready_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    description: Mapped[str | None] = mapped_column(String(1000))
    placed_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("map_issues.id", ondelete="SET NULL", name="fk_files_placed_issue"),
    )
    maintenance_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    maintenance_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(String(128))
    cleaned_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
