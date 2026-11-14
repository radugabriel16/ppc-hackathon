"""Meter and meter-reading models."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class Meter(UUIDPkMixin, Base):
    __tablename__ = "meters"

    external_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )


class MeterReading(UUIDPkMixin, Base):
    __tablename__ = "meter_readings"
    __table_args__ = (
        UniqueConstraint("meter_id", "reading_key", name="uq_meter_readings_meter_reading_key"),
        CheckConstraint("interval_end > interval_start", name="ck_meter_readings_interval_order"),
        CheckConstraint("energy_kwh >= 0", name="ck_meter_readings_energy_non_negative"),
        Index("ix_meter_readings_meter_interval_end", "meter_id", "interval_end"),
    )

    meter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meters.id", ondelete="RESTRICT"), nullable=False
    )
    reading_key: Mapped[str] = mapped_column(String(256), nullable=False)
    seq: Mapped[int] = mapped_column(nullable=False)
    interval_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    interval_end: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Numeric, nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
