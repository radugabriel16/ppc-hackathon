"""Storage-operation telemetry and synthetic scenario-run records."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin
from app.models.enums import FileCategory, StorageBackend


class StorageOperation(UUIDPkMixin, Base):
    __tablename__ = "storage_operations"

    category: Mapped[FileCategory] = mapped_column(
        Enum(FileCategory, name="file_category"), nullable=False, index=True
    )
    storage: Mapped[StorageBackend] = mapped_column(
        Enum(StorageBackend, name="storage_backend"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scenario_runs.id", ondelete="SET NULL"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, index=True)


class ScenarioRun(UUIDPkMixin, Base):
    __tablename__ = "scenario_runs"

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    counters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
