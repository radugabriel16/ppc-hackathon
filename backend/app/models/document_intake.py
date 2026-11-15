"""Durable intake queue. PII is represented only by HMAC and masked values."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin, utcnow


class DocumentIntakeBatch(UUIDPkMixin, Base):
    __tablename__ = 'document_intake_batches'
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('app_users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default='PROCESSING', index=True)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_linked_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)


class DocumentIntakeItem(UUIDPkMixin, Base):
    __tablename__ = 'document_intake_items'
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('document_intake_batches.id', ondelete='CASCADE'), index=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('files.id', ondelete='RESTRICT'), index=True)
    original_file_name: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default='PROCESSING', index=True)
    review_queue: Mapped[str | None] = mapped_column(String(16), index=True)
    review_reason: Mapped[str | None] = mapped_column(String(64))
    detected_type: Mapped[str | None] = mapped_column(String(64))
    extracted_cnp_hmac: Mapped[str | None] = mapped_column(String(64))
    cnp_masked: Mapped[str | None] = mapped_column(String(16))
    suggested_customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('clients.id'))
    confirmed_type: Mapped[str | None] = mapped_column(String(64))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('clients.id'))
    requested_customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('clients.id'))
    requested_type: Mapped[str | None] = mapped_column(String(64))
    confirm_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('app_users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    error_detail: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=utcnow)
