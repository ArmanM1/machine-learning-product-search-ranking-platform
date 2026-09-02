"""Execution-run manifest contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, SchemaVersion, Sha256, UtcDateTime


class RunManifest(ContractModel):
    """Trace a local or cloud job to its inputs, environment, and outputs."""

    schema_version: SchemaVersion
    run_id: NonEmptyStr
    run_type: Literal[
        "data_preparation",
        "baseline",
        "training",
        "evaluation",
        "serving_build",
        "smoke_test",
    ]
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$", min_length=7, max_length=64)]
    repository_dirty: bool
    image_uri: NonEmptyStr
    image_digest: Sha256
    config_hash: Sha256
    dataset_manifest_hash: Sha256
    cloud_project_alias: NonEmptyStr
    region: NonEmptyStr
    job_id: NonEmptyStr
    hardware: NonEmptyStr
    accelerator: NonEmptyStr | None
    started_at: UtcDateTime
    ended_at: UtcDateTime | None
    duration_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    failure_summary: NonEmptyStr | None
    artifact_uris: dict[NonEmptyStr, NonEmptyStr]
    artifact_checksums: dict[NonEmptyStr, Sha256]
    estimated_cost_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    actual_cost_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None

    @model_validator(mode="after")
    def validate_lifecycle_and_artifacts(self) -> RunManifest:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must be on or after started_at")
        if self.status in {"succeeded", "failed", "cancelled"} and (
            self.ended_at is None or self.duration_seconds is None
        ):
            raise ValueError("terminal runs require ended_at and duration_seconds")
        if self.status == "failed" and self.failure_summary is None:
            raise ValueError("failed runs require failure_summary")
        if set(self.artifact_uris) != set(self.artifact_checksums):
            raise ValueError("every artifact URI must have a same-key SHA-256 checksum")
        return self


__all__ = ["RunManifest"]
