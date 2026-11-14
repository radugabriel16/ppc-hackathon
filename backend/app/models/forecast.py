import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class SegmentThreshold(Base):
    __tablename__ = "segment_thresholds"
    __table_args__ = (CheckConstraint("daily_energy_kwh > 0", name="ck_segment_threshold_positive"),)

    segment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subregions.id"), primary_key=True)
    daily_energy_kwh: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="UNCONFIGURED")
    calibration: Mapped[dict | None] = mapped_column(JSONB)


class ForecastRun(UUIDPkMixin, Base):
    __tablename__ = "forecast_runs"

    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"))
    segment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subregions.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String)
