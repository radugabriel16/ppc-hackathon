"""Drone video inspection model."""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class VideoInspection(UUIDPkMixin, Base):
    __tablename__ = "video_inspections"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
