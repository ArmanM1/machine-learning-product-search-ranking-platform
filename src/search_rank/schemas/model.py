"""Immutable model artifact contract."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, SchemaVersion, Sha256, UtcDateTime


class ModelArtifact(ContractModel):
    schema_version: SchemaVersion
    model_id: NonEmptyStr
    run_id: NonEmptyStr
    base_model_id: NonEmptyStr
    base_model_revision: NonEmptyStr
    tokenizer_revision: NonEmptyStr
    checkpoint_uri: NonEmptyStr
    artifact_checksum: Sha256
    artifact_size_bytes: Annotated[int, Field(ge=0)]
    input_contract_version: NonEmptyStr
    label_mapping_version: NonEmptyStr
    promoted: bool
    promotion_reason: NonEmptyStr
    evaluation_report_id: NonEmptyStr
    created_at: UtcDateTime

    @model_validator(mode="after")
    def promoted_artifacts_use_project_mapping(self) -> ModelArtifact:
        if self.promoted and self.label_mapping_version != "project_graded_v1":
            raise ValueError("promoted artifacts must use project_graded_v1")
        return self


__all__ = ["ModelArtifact"]
