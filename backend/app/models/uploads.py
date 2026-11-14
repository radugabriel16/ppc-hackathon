"""Resumable multipart upload session and part tracking (section 5 protocol)."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin
from app.models.enums import FileCategory


class UploadSession(UUIDPkMixin, Base):
    __tablename__ = "upload_sessions"

    category: Mapped[FileCategory] = mapped_column(
        Enum(FileCategory, name="file_category"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_parts: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_upload_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, index=True)


class UploadPart(Base):
    __tablename__ = "upload_parts"

    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upload_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    part_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
