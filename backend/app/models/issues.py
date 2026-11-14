"""Map issue model (operator-reported problems pinned to a network asset)."""
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Date, Enum, ForeignKey, Integer, String, TIMESTAMP, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin
from app.models.enums import IssueSeverity, IssueStatus, IssueType


class MapIssue(UUIDPkMixin, Base):
    __tablename__ = "map_issues"

    is_historical: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), index=True)
    type: Mapped[IssueType] = mapped_column(
        Enum(IssueType, name="issue_type"), default=IssueType.OUTAGE_REPORT,
        server_default="OUTAGE_REPORT", nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, default="Outage report", server_default="Outage report")
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regions.id"), index=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id"), index=True)
    meter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meters.id"), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"), index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connection_cases.id"), index=True)
    forecast_date = mapped_column(Date, nullable=True)
    subregion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subregions.id", ondelete="SET NULL"), index=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    video_inspection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("video_inspections.id", ondelete="SET NULL"), nullable=True
    )
    video_offset_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, name="issue_severity"), nullable=False
    )
    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, name="issue_status"), nullable=False, default=IssueStatus.OPEN
    )
    assigned_team_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
