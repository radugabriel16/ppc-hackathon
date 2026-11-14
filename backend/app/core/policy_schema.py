"""Pydantic model + validation + loader for `config/policies.yaml` (PHASE1.md section 4)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import FileCategory, StorageBackend

ONE_MIB = 1024 * 1024


class CategoryPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    backend: StorageBackend
    fallback: StorageBackend | None = None
    max_size_bytes: int = Field(alias="maxSizeBytes", gt=0)
    max_concurrency: int = Field(alias="maxConcurrency", gt=0)
    encryption: Literal["aes-256-gcm"] | None = None
    resumable: bool = False
    chunk_size_bytes: int | None = Field(default=None, alias="chunkSizeBytes", gt=0)

    @model_validator(mode="after")
    def _check_consistency(self) -> "CategoryPolicy":
        if self.resumable and self.backend != StorageBackend.s3:
            raise ValueError("resumable is only allowed when backend is 's3'")
        if self.backend == StorageBackend.db and self.max_size_bytes > ONE_MIB:
            raise ValueError("backend 'db' only allowed when maxSizeBytes <= 1 MiB (1048576)")
        if self.fallback is not None and self.fallback == self.backend:
            raise ValueError("fallback must differ from backend")
        return self


class PoliciesConfig(BaseModel):
    categories: dict[FileCategory, CategoryPolicy]

    @model_validator(mode="after")
    def _check_all_categories_present(self) -> "PoliciesConfig":
        missing = set(FileCategory) - set(self.categories)
        if missing:
            raise ValueError(f"policies.yaml is missing categories: {sorted(m.value for m in missing)}")
        return self


def load_policies(path: str | Path) -> PoliciesConfig:
    """Load and validate the policy file. Raises ValueError/pydantic ValidationError on problems."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return PoliciesConfig.model_validate(raw)
