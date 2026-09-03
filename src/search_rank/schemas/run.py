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
    device_type: Literal["cpu", "cuda", "mps"] | None = None
    cuda_available: bool | None = None
    cuda_device_count: Annotated[int, Field(ge=0)] | None = None
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
        device_fields = (self.device_type, self.cuda_available, self.cuda_device_count)
        if self.run_type == "training" and any(value is None for value in device_fields):
            raise ValueError("training runs require actual device and CUDA evidence")
        if any(value is not None for value in device_fields):
            if any(value is None for value in device_fields):
                raise ValueError("device and CUDA evidence must be recorded together")
            device_type = self.device_type
            cuda_available = self.cuda_available
            cuda_device_count = self.cuda_device_count
            assert device_type is not None
            assert cuda_available is not None
            assert cuda_device_count is not None
            if cuda_available != (cuda_device_count > 0):
                raise ValueError("CUDA availability and device count differ")
            if (device_type == "cuda") != (self.accelerator == "gpu"):
                raise ValueError("actual device and accelerator differ")
            if device_type == "cuda" and not cuda_available:
                raise ValueError("CUDA execution requires an available CUDA device")
        return self


__all__ = ["RunManifest"]
