import json
from uuid import UUID

from pydantic import field_validator

from app.core.api import ApiModel
from app.models.enums import AssetType


class RegionResource(ApiModel):
    id: UUID
    code: str
    name: str
    center: dict | None
    bounds: dict | None

    @field_validator("center", mode="before")
    @classmethod
    def parse_center(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class AssetResource(ApiModel):
    id: UUID
    region_id: UUID
    code: str
    name: str
    type: AssetType
    rated_capacity_kw: float | None


class MeterResource(ApiModel):
    id: UUID
    external_code: str
    asset_id: UUID
    client_id: UUID | None
