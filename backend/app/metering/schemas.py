from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, TypeAdapter, field_serializer, model_validator

from app.core.api import ApiModel

aware_datetime = TypeAdapter(AwareDatetime)


class MeterReadingIngest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    meter_external_code: str = Field(min_length=1, max_length=64)
    reading_key: str = Field(min_length=1, max_length=256)
    seq: int = Field(strict=True, ge=-(2**31), le=2**31 - 1)
    interval_start: AwareDatetime
    interval_end: AwareDatetime
    energy_kwh: Decimal = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_interval_and_key(self):
        if self.interval_end <= self.interval_start:
            raise ValueError("intervalEnd must be after intervalStart")
        prefix = f"{self.meter_external_code}:"
        if not self.reading_key.startswith(prefix):
            raise ValueError("readingKey must be <meterExternalCode>:<intervalStart ISO>")
        timestamp = self.reading_key[len(prefix):]
        if "T" not in timestamp or aware_datetime.validate_python(timestamp) != self.interval_start:
            raise ValueError("readingKey must contain intervalStart")
        return self


class MeterReadingResource(ApiModel):
    id: UUID
    meter_id: UUID
    reading_key: str
    seq: int
    interval_start: datetime
    interval_end: datetime
    energy_kwh: Decimal
    received_at: datetime

    @field_serializer("energy_kwh")
    def serialize_energy(self, value: Decimal) -> float:
        return float(value)


class MeterReadingListResource(MeterReadingResource):
    meter_code: str
    segment_id: UUID | None
    segment_code: str | None
    segment_name: str | None
