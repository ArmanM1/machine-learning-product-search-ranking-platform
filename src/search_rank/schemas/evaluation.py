"""Machine-readable evaluation evidence contracts."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, SchemaVersion, UtcDateTime
from .model import ModelArtifact

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
ExampleCategory = Literal[
    "win", "loss", "tie_or_uncertain", "lexical_preferred", "complement_exact_confusion"
]
HELDOUT_REQUIRED_EXAMPLE_COUNTS: dict[ExampleCategory, int] = {
    "win": 5,
    "loss": 5,
    "tie_or_uncertain": 3,
    "lexical_preferred": 1,
    "complement_exact_confusion": 1,
}


class MetricResult(ContractModel):
    metric_name: NonEmptyStr
    value: FiniteFloat
    query_count: Count
    excluded_query_count: Count = 0


class PrimaryMetricResult(ContractModel):
    metric_name: Literal["graded_ndcg@10"] = "graded_ndcg@10"
    candidate_value: UnitFloat
    baseline_values: dict[NonEmptyStr, UnitFloat]
    strongest_baseline_id: NonEmptyStr
    strongest_baseline_value: UnitFloat
    candidate_minus_baseline: FiniteFloat

    @model_validator(mode="after")
    def strongest_baseline_is_declared(self) -> PrimaryMetricResult:
        if self.strongest_baseline_id not in self.baseline_values:
            raise ValueError("strongest_baseline_id is missing from baseline_values")
        expected = self.baseline_values[self.strongest_baseline_id]
        if abs(expected - self.strongest_baseline_value) > 1e-12:
            raise ValueError("strongest_baseline_value does not match baseline_values")
        if (
            abs(
                self.candidate_value - self.strongest_baseline_value - self.candidate_minus_baseline
            )
            > 1e-9
        ):
            raise ValueError("candidate_minus_baseline is inconsistent")
        return self


class PairedDifference(ContractModel):
    metric_name: NonEmptyStr
    candidate_model_id: NonEmptyStr
    baseline_model_id: NonEmptyStr
    point_estimate: FiniteFloat
    ci_lower: FiniteFloat
    ci_upper: FiniteFloat
    confidence_level: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]
    query_count: Annotated[int, Field(ge=1)]
    excluded_query_count: Count = 0
    bootstrap_seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    bootstrap_resamples: Annotated[int, Field(ge=1)]
    resampling_unit: Literal["query"] = "query"

    @model_validator(mode="after")
    def ordered_interval(self) -> PairedDifference:
        if self.ci_lower > self.ci_upper:
            raise ValueError("ci_lower must not exceed ci_upper")
        return self


class SliceResult(ContractModel):
    dimension: NonEmptyStr
    slice_name: NonEmptyStr
    query_count: Count
    excluded_query_count: Count
    candidate_value: FiniteFloat | None
    baseline_value: FiniteFloat | None
    point_estimate: FiniteFloat | None
    ci_lower: FiniteFloat | None
    ci_upper: FiniteFloat | None
    adequate_sample_size: bool
    finding: Literal["improvement", "regression", "uncertain", "insufficient_data"]

    @model_validator(mode="after")
    def interval_is_complete_and_ordered(self) -> SliceResult:
        interval = (self.ci_lower, self.ci_upper)
        if (interval[0] is None) != (interval[1] is None):
            raise ValueError("slice confidence interval must have both bounds or neither")
        if interval[0] is not None and interval[1] is not None and interval[0] > interval[1]:
            raise ValueError("ci_lower must not exceed ci_upper")
        return self


class ExampleResult(ContractModel):
    query_id: NonEmptyStr
    category: ExampleCategory
    baseline_metric: FiniteFloat
    candidate_metric: FiniteFloat
    delta: FiniteFloat
    selection_rule: NonEmptyStr
    public_product_ids: list[NonEmptyStr] = Field(default_factory=list)
    notes: NonEmptyStr | None = None

    @model_validator(mode="after")
    def metric_delta_is_consistent(self) -> ExampleResult:
        if abs(self.candidate_metric - self.baseline_metric - self.delta) > 1e-9:
            raise ValueError("example delta must equal candidate_metric - baseline_metric")
        if self.category == "win" and self.delta <= 0:
            raise ValueError("win examples require a positive delta")
        if self.category == "loss" and self.delta >= 0:
            raise ValueError("loss examples require a negative delta")
        return self


class LatencyResult(ContractModel):
    phase: Literal[
        "cold_model_load",
        "first_request",
        "warm_end_to_end",
        "model_inference",
        "serialization",
    ]
    # Offline benchmark groups may exceed the public API's separate 40-candidate cap.
    candidate_count: Annotated[int, Field(ge=1)] | None
    concurrency: Annotated[int, Field(ge=1)] | None
    sample_count: Annotated[int, Field(ge=1)]
    p50_ms: NonNegativeFloat
    p95_ms: NonNegativeFloat
    p99_ms: NonNegativeFloat
    mean_ms: NonNegativeFloat
    lambda_memory_mb: Annotated[int, Field(ge=128)] | None
    architecture: NonEmptyStr
    region: NonEmptyStr
    reserved_concurrency: Annotated[int, Field(ge=0)] | None
    model_revision: NonEmptyStr

    @model_validator(mode="after")
    def percentiles_are_monotonic(self) -> LatencyResult:
        if not self.p50_ms <= self.p95_ms <= self.p99_ms:
            raise ValueError("latency percentiles must satisfy p50 <= p95 <= p99")
        return self


class MemoryResult(ContractModel):
    peak_resident_memory_mb: NonNegativeFloat
    model_artifact_size_bytes: Annotated[int, Field(ge=0)]
    measurement_method: NonEmptyStr


class RuntimeResult(ContractModel):
    duration_seconds: NonNegativeFloat
    hardware: NonEmptyStr
    measured: bool


class CostEvidence(ContractModel):
    estimated_cost_usd: NonNegativeFloat
    actual_cost_usd: NonNegativeFloat | None
    source: NonEmptyStr
    currency: Literal["USD"] = "USD"


class ReleaseGateCheck(ContractModel):
    name: NonEmptyStr
    passed: bool
    detail: NonEmptyStr


class ReleaseGateResult(ContractModel):
    passed: bool
    decision: Literal["promote_candidate", "retain_baseline"]
    candidate_model_id: NonEmptyStr
    baseline_model_id: NonEmptyStr
    promoted_model_id: NonEmptyStr
    positive_claim_allowed: bool
    negative_result_required: bool
    checks: list[ReleaseGateCheck]
    reasons: list[NonEmptyStr]

    @model_validator(mode="after")
    def decision_is_fail_closed(self) -> ReleaseGateResult:
        expected_decision = "promote_candidate" if self.passed else "retain_baseline"
        expected_model = self.candidate_model_id if self.passed else self.baseline_model_id
        if self.decision != expected_decision or self.promoted_model_id != expected_model:
            raise ValueError("release decision/model must follow the aggregate gate outcome")
        if self.positive_claim_allowed != self.passed:
            raise ValueError("positive_claim_allowed must equal passed")
        if self.negative_result_required == self.passed:
            raise ValueError("negative_result_required must be the inverse of passed")
        return self


class EvaluationReport(ContractModel):
    schema_version: SchemaVersion
    report_id: NonEmptyStr
    run_id: NonEmptyStr
    candidate_model_id: NonEmptyStr
    baseline_model_ids: list[NonEmptyStr] = Field(min_length=1)
    split: NonEmptyStr
    test_access_count: Count
    query_count: Count
    excluded_query_count: Count
    metric_definition_version: Literal["project_graded_v1"]
    primary_metric: PrimaryMetricResult
    secondary_metrics: dict[NonEmptyStr, MetricResult]
    system_metrics: dict[NonEmptyStr, dict[NonEmptyStr, MetricResult]] = Field(default_factory=dict)
    paired_differences: list[PairedDifference]
    bootstrap_method: Literal["paired_nonparametric_percentile"]
    bootstrap_seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    bootstrap_resamples: Annotated[int, Field(ge=1)]
    confidence_level: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]
    slice_results: list[SliceResult]
    example_results: list[ExampleResult]
    latency_results: list[LatencyResult]
    memory_results: MemoryResult
    training_runtime: RuntimeResult
    evaluation_runtime: RuntimeResult
    cost_evidence: CostEvidence
    release_gate_results: ReleaseGateResult
    limitations: list[NonEmptyStr]
    created_at: UtcDateTime

    @model_validator(mode="after")
    def evidence_references_declared_models(self) -> EvaluationReport:
        if len(self.baseline_model_ids) != len(set(self.baseline_model_ids)):
            raise ValueError("baseline_model_ids must be unique")
        if self.primary_metric.strongest_baseline_id not in self.baseline_model_ids:
            raise ValueError("primary metric references an undeclared baseline")
        if self.release_gate_results.candidate_model_id != self.candidate_model_id:
            raise ValueError("release gate references a different candidate")
        if self.release_gate_results.baseline_model_id not in self.baseline_model_ids:
            raise ValueError("release gate references an undeclared baseline")
        declared_systems = {self.candidate_model_id, *self.baseline_model_ids}
        if self.system_metrics and set(self.system_metrics) != declared_systems:
            raise ValueError("system_metrics must cover the candidate and every baseline")
        for metrics in self.system_metrics.values():
            if any(name != metric.metric_name for name, metric in metrics.items()):
                raise ValueError("system metric keys must match metric_name values")
        if self.split.casefold() == "test":
            if self.test_access_count < 1:
                raise ValueError("held-out reports require a positive test_access_count")
            if self.bootstrap_resamples < 10_000:
                raise ValueError("held-out reports require at least 10,000 bootstrap resamples")
            category_counts = Counter(item.category for item in self.example_results)
            shortages = [
                f"{category} required={required} available={category_counts[category]}"
                for category, required in HELDOUT_REQUIRED_EXAMPLE_COUNTS.items()
                if category_counts[category] < required
            ]
            if shortages:
                raise ValueError(
                    "held-out representative-example requirements are incomplete: "
                    + "; ".join(shortages)
                )
            identities = [(item.category, item.query_id) for item in self.example_results]
            if len(identities) != len(set(identities)):
                raise ValueError(
                    "held-out representative examples must have unique category/query pairs"
                )
        return self


__all__ = [
    "HELDOUT_REQUIRED_EXAMPLE_COUNTS",
    "CostEvidence",
    "EvaluationReport",
    "ExampleResult",
    "LatencyResult",
    "MemoryResult",
    "MetricResult",
    "ModelArtifact",
    "PairedDifference",
    "PrimaryMetricResult",
    "ReleaseGateCheck",
    "ReleaseGateResult",
    "RuntimeResult",
    "SliceResult",
]
