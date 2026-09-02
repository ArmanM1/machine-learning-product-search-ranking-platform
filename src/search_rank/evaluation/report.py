"""Helpers for assembling internally consistent evaluation evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from search_rank.schemas.evaluation import EvaluationReport, PrimaryMetricResult
from search_rank.schemas.public import redact_for_public


def select_strongest_baseline(baseline_values: Mapping[str, float]) -> tuple[str, float]:
    """Select maximum validation performance with deterministic model-ID ties."""

    if not baseline_values:
        raise ValueError("at least one unchanged baseline metric is required")
    checked: list[tuple[str, float]] = []
    for model_id, value in baseline_values.items():
        if not model_id.strip():
            raise ValueError("baseline model IDs must be non-empty")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0 <= numeric <= 1:
            raise ValueError("baseline nDCG values must be finite and in [0, 1]")
        checked.append((model_id, numeric))
    # ID ascending makes a tied selection independent of mapping insertion order.
    return min(checked, key=lambda item: (-item[1], item[0]))


def build_primary_metric(
    candidate_value: float,
    baseline_values: Mapping[str, float],
) -> PrimaryMetricResult:
    candidate = float(candidate_value)
    if not math.isfinite(candidate) or not 0 <= candidate <= 1:
        raise ValueError("candidate nDCG must be finite and in [0, 1]")
    baseline_id, baseline_value = select_strongest_baseline(baseline_values)
    return PrimaryMetricResult(
        candidate_value=candidate,
        baseline_values=dict(baseline_values),
        strongest_baseline_id=baseline_id,
        strongest_baseline_value=baseline_value,
        candidate_minus_baseline=candidate - baseline_value,
    )


def validate_report_consistency(report: EvaluationReport) -> None:
    """Validate cross-field facts that are awkward to express in JSON Schema."""

    gate = report.release_gate_results
    if gate.baseline_model_id != report.primary_metric.strongest_baseline_id:
        raise ValueError("release gate must compare the strongest unchanged baseline")
    primary_intervals = [
        interval
        for interval in report.paired_differences
        if interval.metric_name == "graded_ndcg@10"
        and interval.baseline_model_id == report.primary_metric.strongest_baseline_id
    ]
    if len(primary_intervals) != 1:
        raise ValueError("exactly one primary paired interval is required")
    interval = primary_intervals[0]
    if interval.bootstrap_seed != report.bootstrap_seed:
        raise ValueError("primary interval and report bootstrap seeds differ")
    if interval.bootstrap_resamples != report.bootstrap_resamples:
        raise ValueError("primary interval and report resample counts differ")
    if abs(interval.confidence_level - report.confidence_level) > 1e-12:
        raise ValueError("primary interval and report confidence levels differ")
    if abs(interval.point_estimate - report.primary_metric.candidate_minus_baseline) > 1e-9:
        raise ValueError("primary interval point estimate differs from aggregate delta")
    if report.split.casefold() == "test" and report.test_access_count < 1:
        raise ValueError("held-out reports require a positive test-access count")


def public_evaluation_outcome(report: EvaluationReport) -> dict[str, object]:
    """Return an allowlisted outcome that keeps negative results visible."""

    validate_report_consistency(report)
    gate = report.release_gate_results
    outcome = {
        "report_id": report.report_id,
        "run_id": report.run_id,
        "candidate_model_id": report.candidate_model_id,
        "baseline_model_ids": list(report.baseline_model_ids),
        "split": report.split,
        "test_access_count": report.test_access_count,
        "query_count": report.query_count,
        "excluded_query_count": report.excluded_query_count,
        "metric_definition_version": report.metric_definition_version,
        "primary_metric": report.primary_metric.model_dump(mode="json"),
        "paired_differences": [
            value.model_dump(mode="json") for value in report.paired_differences
        ],
        "slice_results": [value.model_dump(mode="json") for value in report.slice_results],
        "example_results": [value.model_dump(mode="json") for value in report.example_results],
        "release_gate_results": gate.model_dump(mode="json"),
        "result_kind": "positive_result" if gate.passed else "negative_result",
        "limitations": list(report.limitations),
        "created_at": report.created_at.isoformat(),
    }
    return cast(dict[str, object], redact_for_public(outcome))


__all__ = [
    "build_primary_metric",
    "public_evaluation_outcome",
    "select_strongest_baseline",
    "validate_report_consistency",
]
