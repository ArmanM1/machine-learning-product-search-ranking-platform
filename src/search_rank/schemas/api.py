"""Versioned public HTTP request and response contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, Sha256, UtcDateTime

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
PublicMetricName = Literal[
    "graded_ndcg@10",
    "exact_mrr@10",
    "recall_exact_or_substitute@10",
    "pairwise_ordinal_accuracy",
    "graded_ndcg@5",
    "exact_top_1_rate",
]

_PUBLIC_URI = re.compile(r"\b[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_PUBLIC_ARN = re.compile(r"\barn:(?:aws|aws-us-gov|aws-cn):", re.IGNORECASE)
_PUBLIC_ACCOUNT = re.compile(r"\b\d{12}\b")
_WINDOWS_PATH = re.compile(r"(?:^|[\s'\"(=])(?:[a-z]:[\\/]|\\\\|//)", re.IGNORECASE)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s'\"(=])/[a-z0-9._-]+(?=$|[/\\?#\s'\"),;])",
    re.IGNORECASE,
)


def _public_strings(value: object, location: str = "evidence") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(location, value)]
    if isinstance(value, Mapping):
        output: list[tuple[str, str]] = []
        for key, item in value.items():
            output.extend(_public_strings(item, f"{location}.{key}"))
        return output
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        output = []
        for index, item in enumerate(value):
            output.extend(_public_strings(item, f"{location}[{index}]"))
        return output
    return []


def _reject_private_public_text(value: object) -> None:
    """Fail closed if an allowlisted evidence field still contains a private locator."""

    for location, text in _public_strings(value):
        if (
            _PUBLIC_URI.search(text)
            or _PUBLIC_ARN.search(text)
            or _PUBLIC_ACCOUNT.search(text)
            or _WINDOWS_PATH.search(text)
            or _POSIX_ABSOLUTE_PATH.search(text)
        ):
            raise ValueError(f"{location} contains a prohibited URI, account ID, or local path")


class HealthResponse(ContractModel):
    status: Literal["ok"] = "ok"
    service_version: NonEmptyStr


class ReadyResponse(ContractModel):
    status: Literal["ready"] = "ready"
    model_id: NonEmptyStr
    dataset_manifest_hash: Sha256


class CuratedQuerySummary(ContractModel):
    query_id: NonEmptyStr
    query: NonEmptyStr
    candidate_count: Annotated[int, Field(ge=1, le=40)]


class RankRequest(ContractModel):
    query_id: NonEmptyStr
    model_id: NonEmptyStr
    top_k: Annotated[int, Field(ge=1, le=40)] = 10


class RankedProduct(ContractModel):
    rank: Annotated[int, Field(ge=1, le=40)]
    product_id: NonEmptyStr
    title: NonEmptyStr
    score: FiniteFloat


class RankResponse(ContractModel):
    request_id: NonEmptyStr
    query_id: NonEmptyStr
    query: NonEmptyStr
    model_id: NonEmptyStr
    model_artifact_checksum: Sha256
    dataset_manifest_hash: Sha256
    candidate_count: Annotated[int, Field(ge=1, le=40)]
    top_k: Annotated[int, Field(ge=1, le=40)]
    latency_ms: NonNegativeFloat
    results: list[RankedProduct]

    @model_validator(mode="after")
    def response_counts_and_ranks_are_consistent(self) -> RankResponse:
        if self.top_k > self.candidate_count:
            raise ValueError("top_k cannot exceed candidate_count")
        if len(self.results) > self.top_k:
            raise ValueError("results cannot contain more than top_k products")
        ranks = [result.rank for result in self.results]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("result ranks must be contiguous and start at one")
        return self


class RankMovement(ContractModel):
    product_id: NonEmptyStr
    baseline_rank: Annotated[int, Field(ge=1, le=40)]
    candidate_rank: Annotated[int, Field(ge=1, le=40)]
    rank_delta: Annotated[int, Field(ge=-39, le=39)]

    @model_validator(mode="after")
    def delta_matches_ranks(self) -> RankMovement:
        if self.rank_delta != self.baseline_rank - self.candidate_rank:
            raise ValueError("rank_delta must be baseline_rank - candidate_rank")
        return self


class BenchmarkJudgment(ContractModel):
    product_id: NonEmptyStr
    esci_label: Literal["Exact", "Substitute", "Complement", "Irrelevant"]
    source: Literal["ground_truth_annotation"] = "ground_truth_annotation"


class ComparisonResponse(ContractModel):
    request_id: NonEmptyStr
    query_id: NonEmptyStr
    query: NonEmptyStr
    baseline_model_id: NonEmptyStr
    candidate_model_id: NonEmptyStr
    candidate_count: Annotated[int, Field(ge=1, le=40)]
    baseline_latency_ms: NonNegativeFloat
    candidate_latency_ms: NonNegativeFloat
    baseline_results: list[RankedProduct]
    candidate_results: list[RankedProduct]
    rank_movements: list[RankMovement]
    benchmark_judgments: list[BenchmarkJudgment] | None = None

    @model_validator(mode="after")
    def comparison_uses_identical_products(self) -> ComparisonResponse:
        baseline_ids = [result.product_id for result in self.baseline_results]
        candidate_ids = [result.product_id for result in self.candidate_results]
        if len(baseline_ids) != len(set(baseline_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("comparison rankings cannot contain duplicate products")
        if set(baseline_ids) != set(candidate_ids):
            raise ValueError("comparison systems must expose identical products")
        movement_ids = [movement.product_id for movement in self.rank_movements]
        if set(movement_ids) != set(baseline_ids) or len(movement_ids) != len(set(movement_ids)):
            raise ValueError("rank_movements must cover each compared product exactly once")
        if self.benchmark_judgments is not None:
            judged_ids = [judgment.product_id for judgment in self.benchmark_judgments]
            if len(judged_ids) != len(set(judged_ids)) or not set(judged_ids) <= set(baseline_ids):
                raise ValueError("benchmark judgments must be unique compared products")
        return self


class ModelSummary(ContractModel):
    model_id: NonEmptyStr
    display_name: NonEmptyStr
    kind: NonEmptyStr
    base_model_id: NonEmptyStr | None
    artifact_checksum: Sha256
    evaluation_report_id: NonEmptyStr
    promoted_at: UtcDateTime | None
    limitations_url: NonEmptyStr


class PublicInterval(ContractModel):
    point_estimate: FiniteFloat
    lower: FiniteFloat
    upper: FiniteFloat
    confidence_level: Annotated[float, Field(gt=0, lt=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def interval_is_ordered(self) -> PublicInterval:
        if self.lower > self.upper:
            raise ValueError("lower must not exceed upper")
        return self


class PublicMetricValue(ContractModel):
    metric: PublicMetricName
    display_name: NonEmptyStr
    value: FiniteFloat
    interval: PublicInterval | None = None


class PublicModelMetricRow(ContractModel):
    """Measured model values only; unavailable measurements stay null."""

    model_id: NonEmptyStr
    display_name: NonEmptyStr
    kind: Literal["bm25", "pretrained", "fine_tuned"]
    graded_ndcg_at_10: UnitFloat
    exact_mrr_at_10: UnitFloat | None = None
    recall_exact_or_substitute_at_10: UnitFloat | None = None
    pairwise_ordinal_accuracy: UnitFloat | None = None
    graded_ndcg_at_5: UnitFloat | None = None
    exact_top_1_rate: UnitFloat | None = None
    p95_inference_latency_ms: NonNegativeFloat | None = None


class PublicMetricComparison(ContractModel):
    metric: PublicMetricName
    display_name: NonEmptyStr
    baseline: FiniteFloat
    candidate: FiniteFloat
    delta: FiniteFloat

    @model_validator(mode="after")
    def delta_is_exact(self) -> PublicMetricComparison:
        if abs(self.candidate - self.baseline - self.delta) > 1e-9:
            raise ValueError("metric delta must equal candidate - baseline")
        return self


class PublicEvaluationEvidence(ContractModel):
    evidence_mode: Literal["verified"] = "verified"
    report_id: NonEmptyStr
    run_id: NonEmptyStr
    candidate_model_id: NonEmptyStr
    strongest_baseline_model_id: NonEmptyStr
    release_status: Literal["passed", "failed"]
    primary_metric: PublicMetricValue
    strongest_baseline: PublicMetricValue
    delta: PublicMetricValue
    held_out_query_count: Annotated[int, Field(ge=1)]
    bootstrap_resamples: Annotated[int, Field(ge=10_000)]
    bootstrap_seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    test_access_count: Annotated[int, Field(ge=1)]
    excluded_query_count: Count
    exclusion_note: NonEmptyStr
    models: list[PublicModelMetricRow] = Field(min_length=2)
    secondary_metrics: list[PublicMetricComparison]

    @model_validator(mode="after")
    def evaluation_is_consistent(self) -> PublicEvaluationEvidence:
        for item in (self.primary_metric, self.strongest_baseline, self.delta):
            if item.metric != "graded_ndcg@10":
                raise ValueError("primary, baseline, and delta must use graded_ndcg@10")
        if not 0 <= self.primary_metric.value <= 1:
            raise ValueError("candidate primary metric must be in [0, 1]")
        if not 0 <= self.strongest_baseline.value <= 1:
            raise ValueError("baseline primary metric must be in [0, 1]")
        if self.primary_metric.interval is not None or self.strongest_baseline.interval is not None:
            raise ValueError("only the paired difference may contain the primary interval")
        if self.delta.interval is None:
            raise ValueError("paired primary difference interval is required")
        if abs(self.primary_metric.value - self.strongest_baseline.value - self.delta.value) > 1e-9:
            raise ValueError("primary difference does not match candidate and baseline values")
        if abs(self.delta.interval.point_estimate - self.delta.value) > 1e-9:
            raise ValueError("primary interval point estimate does not match delta")
        if self.release_status == "passed" and (
            self.delta.value <= 0 or self.delta.interval.lower <= 0
        ):
            raise ValueError("a passed release requires a positive paired lower bound")
        model_ids = [model.model_id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("public model metric IDs must be unique")
        if self.candidate_model_id not in model_ids:
            raise ValueError("candidate_model_id is absent from model metrics")
        if self.strongest_baseline_model_id not in model_ids:
            raise ValueError("strongest_baseline_model_id is absent from model metrics")
        metric_names = [metric.metric for metric in self.secondary_metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("public secondary metric names must be unique")
        candidate = next(
            model for model in self.models if model.model_id == self.candidate_model_id
        )
        baseline = next(
            model for model in self.models if model.model_id == self.strongest_baseline_model_id
        )
        if abs(candidate.graded_ndcg_at_10 - self.primary_metric.value) > 1e-9:
            raise ValueError("candidate model metric differs from the primary metric")
        if abs(baseline.graded_ndcg_at_10 - self.strongest_baseline.value) > 1e-9:
            raise ValueError("baseline model metric differs from the primary metric")
        return self


class PublicSliceResult(ContractModel):
    slice_id: NonEmptyStr
    display_name: NonEmptyStr
    description: NonEmptyStr
    query_count: Count
    excluded_query_count: Count
    baseline_graded_ndcg_at_10: UnitFloat | None
    candidate_graded_ndcg_at_10: UnitFloat | None
    delta: FiniteFloat | None
    low_sample: bool
    finding: Literal["improvement", "regression", "uncertain", "insufficient_data"]

    @model_validator(mode="after")
    def slice_values_are_complete(self) -> PublicSliceResult:
        values = (
            self.baseline_graded_ndcg_at_10,
            self.candidate_graded_ndcg_at_10,
            self.delta,
        )
        if any(value is None for value in values) and not all(value is None for value in values):
            raise ValueError("slice baseline, candidate, and delta must be present together")
        if all(value is not None for value in values):
            baseline, candidate, delta = values
            assert baseline is not None and candidate is not None and delta is not None
            if abs(candidate - baseline - delta) > 1e-9:
                raise ValueError("slice delta must equal candidate - baseline")
        if self.low_sample == (self.finding != "insufficient_data"):
            raise ValueError("low_sample must match an insufficient_data finding")
        return self


class PublicFailureExample(ContractModel):
    example_id: NonEmptyStr
    query: CuratedQuerySummary
    category: Literal[
        "win", "loss", "tie_or_uncertain", "lexical_preferred", "complement_exact_confusion"
    ]
    baseline_metric: FiniteFloat
    candidate_metric: FiniteFloat
    delta: FiniteFloat
    selection_rule: NonEmptyStr
    public_product_ids: list[NonEmptyStr] = Field(default_factory=list)
    notes: NonEmptyStr | None = None
    interpretation: NonEmptyStr | None = None
    next_experiment: NonEmptyStr | None = None

    @model_validator(mode="after")
    def example_delta_is_exact(self) -> PublicFailureExample:
        if abs(self.candidate_metric - self.baseline_metric - self.delta) > 1e-9:
            raise ValueError("example delta must equal candidate - baseline")
        if len(self.public_product_ids) != len(set(self.public_product_ids)):
            raise ValueError("public example product IDs must be unique")
        return self


class PublicFailureAnalysis(ContractModel):
    evidence_mode: Literal["verified"] = "verified"
    run_id: NonEmptyStr
    metric: Literal["graded_ndcg@10"] = "graded_ndcg@10"
    minimum_slice_size: Annotated[int, Field(ge=1)]
    slices: list[PublicSliceResult]
    examples: list[PublicFailureExample]


class PublicRunMetrics(ContractModel):
    candidate_graded_ndcg_at_10: UnitFloat
    strongest_baseline_graded_ndcg_at_10: UnitFloat
    candidate_minus_baseline_graded_ndcg_at_10: FiniteFloat

    @model_validator(mode="after")
    def difference_is_exact(self) -> PublicRunMetrics:
        if (
            abs(
                self.candidate_graded_ndcg_at_10
                - self.strongest_baseline_graded_ndcg_at_10
                - self.candidate_minus_baseline_graded_ndcg_at_10
            )
            > 1e-9
        ):
            raise ValueError("run primary difference is inconsistent")
        return self


class PublicRunIntervals(ContractModel):
    candidate_minus_baseline_graded_ndcg_at_10: PublicInterval


class PublicValidationRunMetrics(ContractModel):
    selected_model_graded_ndcg_at_10: UnitFloat


class PublicRunSummary(ContractModel):
    """Allowlisted public evidence; intentionally omits cloud identifiers/URIs."""

    evidence_mode: Literal["verified"] = "verified"
    run_id: NonEmptyStr
    status: Literal["complete"] = "complete"
    config_hash: Sha256
    dataset_manifest_hash: Sha256
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$", min_length=7, max_length=64)]
    image_digest: Sha256
    model_artifact_checksum: Sha256
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    locale: Literal["us"]
    base_model_id: NonEmptyStr
    base_model_revision: NonEmptyStr
    training_strategy: NonEmptyStr
    hardware_class: NonEmptyStr
    region: NonEmptyStr
    metrics: PublicRunMetrics
    intervals: PublicRunIntervals
    duration_seconds: NonNegativeFloat
    actual_cost_usd: NonNegativeFloat | None
    cost_evidence: NonEmptyStr
    test_access_count: Annotated[int, Field(ge=1)]
    limitations: list[NonEmptyStr]
    prohibited_claims: list[NonEmptyStr]
    reproduction_command: NonEmptyStr


class PublicValidationRunSummary(ContractModel):
    """Truthful pre-held-out release metadata for the bootstrap baseline."""

    evidence_mode: Literal["validation_only"] = "validation_only"
    run_id: NonEmptyStr
    status: Literal["validation_only"] = "validation_only"
    selected_model_id: NonEmptyStr
    config_hash: Sha256
    dataset_manifest_hash: Sha256
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$", min_length=7, max_length=64)]
    image_digest: Sha256
    model_artifact_checksum: Sha256
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    locale: Literal["us"]
    base_model_id: NonEmptyStr | None
    hardware_class: NonEmptyStr
    region: NonEmptyStr
    metrics: PublicValidationRunMetrics
    duration_seconds: NonNegativeFloat
    actual_cost_usd: NonNegativeFloat | None
    cost_evidence: NonEmptyStr
    test_access_count: Literal[0] = 0
    held_out_claims_allowed: Literal[False] = False
    validation_only_notice: NonEmptyStr
    limitations: list[NonEmptyStr] = Field(min_length=1)
    prohibited_claims: list[NonEmptyStr] = Field(min_length=1)
    reproduction_command: NonEmptyStr


class PublicValidationEvaluation(ContractModel):
    evidence_mode: Literal["validation_only"] = "validation_only"
    evidence_id: NonEmptyStr
    run_id: NonEmptyStr
    status: Literal["validation_only"] = "validation_only"
    selected_model_id: NonEmptyStr
    primary_metric: PublicMetricValue
    validation_query_count: Annotated[int, Field(ge=1)]
    excluded_query_count: Count
    test_access_count: Literal[0] = 0
    held_out: Literal[False] = False
    models: list[PublicModelMetricRow] = Field(min_length=1)
    selection_note: NonEmptyStr

    @model_validator(mode="after")
    def validation_evidence_is_consistent(self) -> PublicValidationEvaluation:
        if self.primary_metric.metric != "graded_ndcg@10":
            raise ValueError("validation selection metric must be graded_ndcg@10")
        if self.primary_metric.interval is not None:
            raise ValueError("validation-only baseline selection cannot publish a release interval")
        model_ids = [model.model_id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("validation model metric IDs must be unique")
        if self.selected_model_id not in model_ids:
            raise ValueError("selected validation model is absent from model metrics")
        selected = next(model for model in self.models if model.model_id == self.selected_model_id)
        if abs(selected.graded_ndcg_at_10 - self.primary_metric.value) > 1e-9:
            raise ValueError("selected model metric differs from the validation primary metric")
        return self


class PublicValidationFailureAnalysis(ContractModel):
    evidence_mode: Literal["validation_only"] = "validation_only"
    run_id: NonEmptyStr
    status: Literal["not_performed"] = "not_performed"
    reason: NonEmptyStr
    slices: list[PublicSliceResult] = Field(default_factory=list, max_length=0)
    examples: list[PublicFailureExample] = Field(default_factory=list, max_length=0)


class PublicEvidenceEnvelope(ContractModel):
    """Complete public payload loaded from one immutable, pre-generated artifact."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    evidence_mode: Literal["verified", "validation_only"] = "verified"
    run: PublicRunSummary | PublicValidationRunSummary
    evaluation: PublicEvaluationEvidence | PublicValidationEvaluation
    failure_analysis: PublicFailureAnalysis | PublicValidationFailureAnalysis

    @model_validator(mode="after")
    def envelope_is_bound_and_public(self) -> PublicEvidenceEnvelope:
        if len({self.run.run_id, self.evaluation.run_id, self.failure_analysis.run_id}) != 1:
            raise ValueError("run, evaluation, and failure analysis must share one run_id")
        if any(
            item.evidence_mode != self.evidence_mode
            for item in (self.run, self.evaluation, self.failure_analysis)
        ):
            raise ValueError("every public evidence section must match the envelope mode")
        if self.evidence_mode == "validation_only":
            if not isinstance(self.run, PublicValidationRunSummary):
                raise ValueError("validation-only envelope requires validation run evidence")
            if not isinstance(self.evaluation, PublicValidationEvaluation):
                raise ValueError("validation-only envelope requires validation evaluation evidence")
            if not isinstance(self.failure_analysis, PublicValidationFailureAnalysis):
                raise ValueError("validation-only envelope requires explicit analysis status")
            if self.run.selected_model_id != self.evaluation.selected_model_id:
                raise ValueError("validation run and evaluation selected models differ")
            if (
                abs(
                    self.run.metrics.selected_model_graded_ndcg_at_10
                    - self.evaluation.primary_metric.value
                )
                > 1e-9
            ):
                raise ValueError("validation run and evaluation primary metrics differ")
            _reject_private_public_text(self.model_dump(mode="json"))
            return self
        if not isinstance(self.run, PublicRunSummary):
            raise ValueError("verified envelope requires a verified run summary")
        if not isinstance(self.evaluation, PublicEvaluationEvidence):
            raise ValueError("verified envelope requires held-out evaluation evidence")
        if not isinstance(self.failure_analysis, PublicFailureAnalysis):
            raise ValueError("verified envelope requires held-out failure analysis")
        run_metrics = self.run.metrics
        if (
            abs(run_metrics.candidate_graded_ndcg_at_10 - self.evaluation.primary_metric.value)
            > 1e-9
        ):
            raise ValueError("run and evaluation candidate metrics differ")
        if (
            abs(
                run_metrics.strongest_baseline_graded_ndcg_at_10
                - self.evaluation.strongest_baseline.value
            )
            > 1e-9
        ):
            raise ValueError("run and evaluation baseline metrics differ")
        if (
            abs(
                run_metrics.candidate_minus_baseline_graded_ndcg_at_10 - self.evaluation.delta.value
            )
            > 1e-9
        ):
            raise ValueError("run and evaluation deltas differ")
        if (
            self.run.intervals.candidate_minus_baseline_graded_ndcg_at_10
            != self.evaluation.delta.interval
        ):
            raise ValueError("run and evaluation primary intervals differ")
        if self.run.test_access_count != self.evaluation.test_access_count:
            raise ValueError("run and evaluation test-access counts differ")
        _reject_private_public_text(self.model_dump(mode="json"))
        return self


class ApiError(ContractModel):
    status: Annotated[int, Field(ge=400, le=599)]
    code: NonEmptyStr
    message: NonEmptyStr
    request_id: NonEmptyStr
    details: dict[str, Any] | None = None


__all__ = [
    "ApiError",
    "BenchmarkJudgment",
    "ComparisonResponse",
    "CuratedQuerySummary",
    "HealthResponse",
    "ModelSummary",
    "PublicEvaluationEvidence",
    "PublicEvidenceEnvelope",
    "PublicFailureAnalysis",
    "PublicFailureExample",
    "PublicInterval",
    "PublicMetricComparison",
    "PublicMetricName",
    "PublicMetricValue",
    "PublicModelMetricRow",
    "PublicRunIntervals",
    "PublicRunMetrics",
    "PublicRunSummary",
    "PublicSliceResult",
    "PublicValidationEvaluation",
    "PublicValidationFailureAnalysis",
    "PublicValidationRunMetrics",
    "PublicValidationRunSummary",
    "RankMovement",
    "RankRequest",
    "RankResponse",
    "RankedProduct",
    "ReadyResponse",
]
