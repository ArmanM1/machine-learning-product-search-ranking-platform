"""Strict contracts for JSON published by release and baseline workflows."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, Sha256, UtcDateTime
from .evaluation import PairedDifference, PrimaryMetricResult
from .evidence import SourceEvaluation

Count = Annotated[int, Field(ge=0)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
FullGitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
CommandGitSha = Annotated[str, Field(pattern=r"^(?:unavailable|[0-9a-f]{7,64})$")]


class CuratedProductArtifact(ContractModel):
    product_id: NonEmptyStr
    title: NonEmptyStr
    text: NonEmptyStr
    esci_label: Literal["Exact", "Substitute", "Complement", "Irrelevant"] | None = None


class CuratedQueryArtifact(ContractModel):
    query_id: NonEmptyStr
    query: NonEmptyStr
    products: Annotated[list[CuratedProductArtifact], Field(min_length=1, max_length=40)]

    @model_validator(mode="after")
    def products_are_unique(self) -> CuratedQueryArtifact:
        product_ids = [product.product_id for product in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("curated query product IDs must be unique")
        return self


class CuratedQueryCollection(ContractModel):
    schema_version: Literal["1.0.0"]
    queries: Annotated[list[CuratedQueryArtifact], Field(min_length=1)]

    @model_validator(mode="after")
    def query_ids_are_unique(self) -> CuratedQueryCollection:
        query_ids = [query.query_id for query in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("curated query IDs must be unique")
        return self


class CommandRuntime(ContractModel):
    python: NonEmptyStr
    platform: NonEmptyStr


class CommandSummary(ContractModel):
    schema_version: Literal["1.0.0"]
    run_id: NonEmptyStr
    command: NonEmptyStr
    status: Literal["succeeded", "failed"]
    config_path: NonEmptyStr | None
    started_at: UtcDateTime
    ended_at: UtcDateTime
    duration_seconds: NonNegativeFloat
    git_sha: CommandGitSha
    repository_dirty: bool
    runtime: CommandRuntime
    artifact_paths: dict[NonEmptyStr, NonEmptyStr]
    artifact_hashes: dict[NonEmptyStr, Sha256]
    result: dict[str, Any]
    failure: NonEmptyStr | None

    @model_validator(mode="after")
    def lifecycle_and_artifacts_are_consistent(self) -> CommandSummary:
        if self.ended_at < self.started_at:
            raise ValueError("command ended before it started")
        if set(self.artifact_paths) != set(self.artifact_hashes):
            raise ValueError("command artifact paths and checksums differ")
        if self.status == "succeeded" and self.failure is not None:
            raise ValueError("successful command cannot contain a failure")
        if self.status == "failed" and self.failure is None:
            raise ValueError("failed command requires a failure")
        return self


class BaselineSummary(ContractModel):
    schema_version: Literal["1.0.0"]
    config_hash: Sha256
    dataset_manifest_hash: Sha256
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    dataset_locale: Literal["us"]
    split: Literal["validation"]
    metrics: dict[NonEmptyStr, FiniteFloat]
    system_metrics: dict[NonEmptyStr, dict[NonEmptyStr, FiniteFloat]]
    system_metric_query_counts: dict[NonEmptyStr, dict[NonEmptyStr, Count]]
    system_metric_excluded_query_counts: dict[NonEmptyStr, dict[NonEmptyStr, Count]]
    p95_inference_latency_ms: dict[NonEmptyStr, NonNegativeFloat]
    strongest_baseline_id: NonEmptyStr
    strongest_baseline_value: FiniteFloat
    validation_query_count: Annotated[int, Field(ge=1)]
    excluded_query_count: Count
    rankings: dict[NonEmptyStr, NonEmptyStr]
    resumed_from_run_id: NonEmptyStr | None

    @model_validator(mode="after")
    def system_inventory_and_selection_are_exact(self) -> BaselineSummary:
        systems = set(self.system_metrics)
        if not systems or any(
            set(values) != systems
            for values in (
                self.system_metric_query_counts,
                self.system_metric_excluded_query_counts,
                self.p95_inference_latency_ms,
                self.rankings,
            )
        ):
            raise ValueError("baseline evidence system inventories differ")
        if not self.metrics or not set(self.metrics).issubset(systems):
            raise ValueError("competitive baseline metrics are outside the system inventory")
        if self.strongest_baseline_id not in self.metrics:
            raise ValueError("selected baseline is absent from the system inventory")
        if abs(self.metrics[self.strongest_baseline_id] - self.strongest_baseline_value) > 1e-12:
            raise ValueError("selected baseline value differs from metrics")
        return self


class HeldoutAccessCounter(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["heldout_access_counter"]
    count: Annotated[int, Field(ge=1)]
    clean_run: Literal[1, 2]
    candidate_run_id: NonEmptyStr
    code_commit: FullGitSha
    workflow_run_id: Annotated[str, Field(pattern=r"^[0-9]+$")]


class ProcessingJobEvidence(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["heldout_processing_job_evidence"]
    processing_job_name: NonEmptyStr
    status: Literal["Completed"]
    instance_type: Literal["ml.m5.xlarge"]
    instance_count: Literal[1]
    creation_time: UtcDateTime
    end_time: UtcDateTime
    image_digest: Sha256
    region: Literal["us-east-1"]
    clean_run: Literal[1, 2]
    exit_message_present: bool

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> ProcessingJobEvidence:
        if self.end_time < self.creation_time:
            raise ValueError("Processing job ended before it was created")
        return self


class ReleaseSummary(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["heldout_release_summary"]
    report_id: NonEmptyStr
    run_id: NonEmptyStr
    candidate_model_id: NonEmptyStr
    baseline_model_ids: Annotated[list[NonEmptyStr], Field(min_length=1)]
    promoted_model_id: NonEmptyStr
    promotion_decision: Literal["promote_candidate", "retain_baseline"]
    gate_passed: bool
    test_access_count: Annotated[int, Field(ge=1)]
    clean_evaluation_count: Literal[2]
    source_evaluations: Annotated[list[SourceEvaluation], Field(min_length=2, max_length=2)]
    primary_metric: PrimaryMetricResult
    paired_differences: list[PairedDifference]
    code_commit: FullGitSha
    evaluation_image_digest: Sha256
    evaluation_config_hash: Sha256
    trial_selection_id: Annotated[str, Field(pattern=r"^trial-selection-[0-9a-f]{20}$")]
    trial_selection_sha256: Sha256

    @model_validator(mode="after")
    def release_decision_is_truthful(self) -> ReleaseSummary:
        if len(self.baseline_model_ids) != len(set(self.baseline_model_ids)):
            raise ValueError("release summary baseline IDs must be unique")
        expected_decision = "promote_candidate" if self.gate_passed else "retain_baseline"
        expected_model = (
            self.candidate_model_id
            if self.gate_passed
            else self.primary_metric.strongest_baseline_id
        )
        if self.promotion_decision != expected_decision or self.promoted_model_id != expected_model:
            raise ValueError("release summary decision/model differs from its gate")
        return self


class TrialSelectionBinding(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["trial_selection_binding"]
    selection_id: Annotated[str, Field(pattern=r"^trial-selection-[0-9a-f]{20}$")]
    s3_key: Annotated[
        str,
        Field(pattern=r"^runs/trial-selection/trial-selection-[0-9a-f]{20}/trial-selection\.json$"),
    ]
    sha256: Sha256
    split: Literal["validation"]
    trial_count: Literal[3]
    test_access_count: Literal[0]


class TrialSelectionVerification(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["trial_selection_verification"]
    selection_id: Annotated[str, Field(pattern=r"^trial-selection-[0-9a-f]{20}$")]
    status: Literal["verified"]


class PublicationEvidence(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["object_publication_evidence"]
    status: Literal["published"]
    version_id_present: Literal[True]
    etag_present: Literal[True]


__all__ = [
    "BaselineSummary",
    "CommandSummary",
    "CuratedQueryCollection",
    "HeldoutAccessCounter",
    "ProcessingJobEvidence",
    "PublicationEvidence",
    "ReleaseSummary",
    "TrialSelectionBinding",
    "TrialSelectionVerification",
]
