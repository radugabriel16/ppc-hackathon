"""Reminder records for connection cases missing required documents."""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class Reminder(UUIDPkMixin, Base):
    __tablename__ = "reminders"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connection_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    missing_types: Mapped[dict] = mapped_column(JSONB, nullable=False)
