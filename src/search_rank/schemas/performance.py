"""Persisted performance-evidence contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, Sha256, UtcDateTime

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class ColdStartIdentifiers(ContractModel):
    release_id: NonEmptyStr
    model_id: NonEmptyStr
    dataset_manifest_hash: Sha256
    model_artifact_checksum: Sha256
    function_name: NonEmptyStr
    alias: Literal["candidate"]
    function_version: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
    region: Literal["us-east-1"]


class ColdStartControlProof(ContractModel):
    newly_published_after_apply_started: Literal[True]
    candidate_version_changed: Literal[True]
    previous_candidate_version: Annotated[str, Field(pattern=r"^(absent|[1-9][0-9]*)$")]
    new_version_prior_cloudwatch_event_count: Literal[0]
    on_demand_execution: Literal[True]
    reserved_concurrency: Literal[2]
    provisioned_concurrency: Literal[0]


class ColdStartFirstRequest(ContractModel):
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    route: Literal["/api/v1/rank"]
    http_status: Literal[200]
    candidate_count: Annotated[int, Field(ge=1, le=40)]
    end_to_end_latency_ms: PositiveFloat
    model_latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ColdStartLambdaReport(ContractModel):
    init_duration_ms: PositiveFloat
    invocation_duration_ms: PositiveFloat
    billed_duration_ms: PositiveFloat
    configured_memory_mb: Literal[4096]
    max_memory_used_mb: PositiveFloat


class ColdStartStructuredStartup(ContractModel):
    startup_succeeded: Literal[True]
    model_load_duration_ms: PositiveFloat


class ColdStartStructuredRequest(ContractModel):
    process_peak_memory_mb: PositiveFloat


class ColdStartEvidence(ContractModel):
    """One controlled first invocation, intentionally separate from warm samples."""

    schema_version: Literal["1.0.0"]
    status: Literal["measured"]
    measurement_class: Literal["controlled_on_demand_lambda_cold_start"]
    controlled_cold_start: Literal[True]
    measured_at: UtcDateTime
    identifiers: ColdStartIdentifiers
    control_proof: ColdStartControlProof
    first_request: ColdStartFirstRequest
    lambda_report: ColdStartLambdaReport
    structured_startup: ColdStartStructuredStartup
    structured_request: ColdStartStructuredRequest
    sample_count: Literal[1]
    excluded_from_warm_samples: Literal[True]
    limitations: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_versions_and_memory(self) -> ColdStartEvidence:
        previous = self.control_proof.previous_candidate_version
        if previous == self.identifiers.function_version:
            raise ValueError("previous and measured candidate versions must differ")
        if self.lambda_report.max_memory_used_mb > self.lambda_report.configured_memory_mb:
            raise ValueError("Lambda max memory cannot exceed configured memory")
        if self.structured_request.process_peak_memory_mb > self.lambda_report.configured_memory_mb:
            raise ValueError("process peak memory cannot exceed configured memory")
        return self


__all__ = ["ColdStartEvidence"]
