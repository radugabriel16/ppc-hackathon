"""Alerts delivered by the internal Alertmanager webhook."""
from datetime import datetime

from sqlalchemy import TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class Alert(UUIDPkMixin, Base):
    __tablename__ = "alerts"

    severity: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
