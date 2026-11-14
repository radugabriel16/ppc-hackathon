from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.api import ApiModel
from app.models.enums import IssueSeverity, IssueStatus


class GeoPoint(ApiModel):
    type: Literal["Point"]
    coordinates: tuple[
        Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)],
        Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)],
    ]


class IssueCreate(ApiModel):
    asset_id: UUID
    video_inspection_id: UUID | None = None
    video_offset_seconds: int | None = Field(default=None, ge=0)
    location: GeoPoint
    description: str | None = None
    severity: IssueSeverity

    @model_validator(mode="after")
    def validate_video_offset(self):
        if self.video_offset_seconds is not None and self.video_inspection_id is None:
            raise ValueError("videoOffsetSeconds requires videoInspectionId")
        return self


class IssueStatusUpdate(ApiModel):
    status: IssueStatus
    assigned_team_label: str | None = Field(default=None, max_length=128)
    version: int = Field(ge=1)


class IssueResource(ApiModel):
    id: UUID
    subregion_id: UUID | None = None
    asset_id: UUID
    location: GeoPoint
    description: str | None
    severity: IssueSeverity
    status: IssueStatus
    assigned_team_label: str | None
    created_at: datetime
    resolved_at: datetime | None
    version: int
