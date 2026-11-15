from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator

from app.core.api import ApiModel
from app.files.schemas import DroneVideoMetadata
from app.models.enums import FileCategory

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class UploadCreate(ApiModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[FileCategory.DRONE_VIDEO]
    file_name: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(gt=0, strict=True)
    sha256: Sha256 | None = None
    media_type: str | None = Field(default=None, max_length=128, pattern=r"^[\w.+-]+/[\w.+-]+$")
    metadata: DroneVideoMetadata

    @field_validator("file_name")
    @classmethod
    def valid_filename(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid filename")
        return value


class UploadComplete(ApiModel):
    model_config = ConfigDict(extra="forbid")

    sha256: Sha256
