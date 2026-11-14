"""Durable worker scheduling, gap snapshots and at-most-once reminder attempts."""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerState(Base):
    __tablename__ = "worker_state"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    cursor: Mapped[uuid.UUID | None] = mapped_column()


class MeterGap(Base):
    __tablename__ = "meter_gaps"

    meter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meters.id", ondelete="CASCADE"), primary_key=True
    )
    region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), index=True
    )
    missing: Mapped[int] = mapped_column(Integer)
    active_until: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), index=True)


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    attempted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
