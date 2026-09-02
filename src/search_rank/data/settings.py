"""Validated inputs for deterministic ESCI acquisition and preparation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from search_rank.config import load_yaml


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)


class DataPreparationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    dataset_name: str
    dataset_version: str
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_url: HttpUrl
    license_url: HttpUrl
    license_notice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locale: str = "us"
    small_version: int = 1
    validation_fraction: float = Field(gt=0, lt=1)
    validation_salt: str = Field(min_length=8)
    development_query_count: int = Field(ge=1)
    raw_dir: Path
    processed_dir: Path
    sources: dict[str, SourceFile]

    @field_validator("sources")
    @classmethod
    def required_sources(cls, value: dict[str, SourceFile]) -> dict[str, SourceFile]:
        missing = {"examples", "products", "sources"} - set(value)
        if missing:
            raise ValueError(f"missing source definitions: {sorted(missing)}")
        return value


def load_data_config(path: str | Path) -> DataPreparationConfig:
    return DataPreparationConfig.model_validate(load_yaml(path))
