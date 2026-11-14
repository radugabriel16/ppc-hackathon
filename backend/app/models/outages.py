"""Outage record model."""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, TIMESTAMP, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class Outage(UUIDPkMixin, Base):
    __tablename__ = "outages"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
