"""Deterministic projection from internal evaluation artifacts to the public contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from search_rank.schemas.api import (
    CuratedQuerySummary,
    PublicEvaluationEvidence,
    PublicEvidenceEnvelope,
    PublicFailureAnalysis,
    PublicFailureExample,
    PublicInterval,
    PublicMetricComparison,
    PublicMetricName,
    PublicMetricValue,
    PublicModelMetricRow,
    PublicRunIntervals,
    PublicRunMetrics,
    PublicRunSummary,
    PublicSliceResult,
    PublicValidationEvaluation,
    PublicValidationFailureAnalysis,
    PublicValidationRunSummary,
)
from search_rank.schemas.evaluation import EvaluationReport

from .query_store import QueryStore


def _primary_interval(report: EvaluationReport) -> PublicInterval:
    values = [
        interval
        for interval in report.paired_differences
        if interval.metric_name == "graded_ndcg@10"
        and interval.baseline_model_id == report.primary_metric.strongest_baseline_id
    ]
    if len(values) != 1:
        raise ValueError("evaluation report must contain one strongest-baseline primary interval")
    interval = values[0]
    return PublicInterval(
        point_estimate=interval.point_estimate,
        lower=interval.ci_lower,
        upper=interval.ci_upper,
        confidence_level=interval.confidence_level,
    )


def public_run_metrics(report: EvaluationReport) -> PublicRunMetrics:
    primary = report.primary_metric
    return PublicRunMetrics(
        candidate_graded_ndcg_at_10=primary.candidate_value,
        strongest_baseline_graded_ndcg_at_10=primary.strongest_baseline_value,
        candidate_minus_baseline_graded_ndcg_at_10=primary.candidate_minus_baseline,
    )


def public_run_intervals(report: EvaluationReport) -> PublicRunIntervals:
    return PublicRunIntervals(candidate_minus_baseline_graded_ndcg_at_10=_primary_interval(report))


def _model_kind(
    model_id: str, candidate_model_id: str
) -> Literal["bm25", "pretrained", "fine_tuned"]:
    if model_id == candidate_model_id:
        return "fine_tuned"
    if model_id.startswith("bm25-"):
        return "bm25"
    if model_id.startswith("pretrained-cross-encoder@"):
        return "pretrained"
    raise ValueError(f"unsupported public evaluation model: {model_id}")


def _model_name(kind: Literal["bm25", "pretrained", "fine_tuned"]) -> str:
    return {
        "fine_tuned": "Fine-tuned candidate",
        "bm25": "BM25 lexical baseline",
        "pretrained": "Unchanged pretrained cross-encoder",
    }[kind]


_SECONDARY_METRICS: tuple[tuple[PublicMetricName, str], ...] = (
    ("exact_mrr@10", "Exact MRR@10"),
    ("recall_exact_or_substitute@10", "Exact-or-substitute recall@10"),
    ("pairwise_ordinal_accuracy", "Pairwise ordinal accuracy"),
    ("graded_ndcg@5", "Graded nDCG@5"),
    ("exact_top_1_rate", "Exact top-1 rate"),
)


def _system_metric(report: EvaluationReport, model_id: str, name: str) -> float | None:
    value = report.system_metrics[model_id].get(name)
    return value.value if value is not None else None


def _public_models(report: EvaluationReport) -> list[PublicModelMetricRow]:
    expected_ids = {report.candidate_model_id, *report.baseline_model_ids}
    if set(report.system_metrics) != expected_ids:
        raise ValueError("public evidence requires exact metrics for every evaluated system")
    latency_by_model: dict[str, float] = {}
    for model_id in sorted(expected_ids):
        values = [
            result
            for result in report.latency_results
            if result.phase == "model_inference" and result.model_revision == model_id
        ]
        if len(values) != 1:
            raise ValueError(
                f"public evidence requires one inference-latency result for {model_id}"
            )
        latency_by_model[model_id] = values[0].p95_ms
    models = []
    for model_id in sorted(expected_ids):
        kind = _model_kind(model_id, report.candidate_model_id)
        graded_ndcg = _system_metric(report, model_id, "graded_ndcg@10")
        if graded_ndcg is None:
            raise ValueError(f"system {model_id} is missing graded_ndcg@10")
        models.append(
            PublicModelMetricRow(
                model_id=model_id,
                display_name=_model_name(kind),
                kind=kind,
                graded_ndcg_at_10=graded_ndcg,
                exact_mrr_at_10=_system_metric(report, model_id, "exact_mrr@10"),
                recall_exact_or_substitute_at_10=_system_metric(
                    report, model_id, "recall_exact_or_substitute@10"
                ),
                pairwise_ordinal_accuracy=_system_metric(
                    report, model_id, "pairwise_ordinal_accuracy"
                ),
                graded_ndcg_at_5=_system_metric(report, model_id, "graded_ndcg@5"),
                exact_top_1_rate=_system_metric(report, model_id, "exact_top_1_rate"),
                p95_inference_latency_ms=latency_by_model[model_id],
            )
        )
    return models


def _secondary_comparisons(report: EvaluationReport) -> list[PublicMetricComparison]:
    candidate = report.candidate_model_id
    baseline = report.primary_metric.strongest_baseline_id
    comparisons = []
    for name, display_name in _SECONDARY_METRICS:
        candidate_value = _system_metric(report, candidate, name)
        baseline_value = _system_metric(report, baseline, name)
        if candidate_value is None or baseline_value is None:
            continue
        comparisons.append(
            PublicMetricComparison(
                metric=name,
                display_name=display_name,
                baseline=baseline_value,
                candidate=candidate_value,
                delta=candidate_value - baseline_value,
            )
        )
    return comparisons


def _display(value: str) -> str:
    return value.replace("_", " ").replace(":", " · ").strip().capitalize()


def _public_failure_analysis(
    report: EvaluationReport,
    queries: QueryStore,
    *,
    minimum_slice_size: int,
) -> PublicFailureAnalysis:
    slices = [
        PublicSliceResult(
            slice_id=f"{item.dimension}:{item.slice_name}",
            display_name=_display(item.slice_name),
            description=f"Predeclared {_display(item.dimension).casefold()} slice.",
            query_count=item.query_count,
            excluded_query_count=item.excluded_query_count,
            baseline_graded_ndcg_at_10=item.baseline_value,
            candidate_graded_ndcg_at_10=item.candidate_value,
            delta=item.point_estimate,
            low_sample=not item.adequate_sample_size,
            finding=item.finding,
        )
        for item in report.slice_results
    ]
    examples = []
    for item in report.example_results:
        query = queries.get(item.query_id)
        examples.append(
            PublicFailureExample(
                example_id=f"{item.category}:{item.query_id}",
                query=CuratedQuerySummary(
                    query_id=query.query_id,
                    query=query.query,
                    candidate_count=len(query.products),
                ),
                category=item.category,
                baseline_metric=item.baseline_metric,
                candidate_metric=item.candidate_metric,
                delta=item.delta,
                selection_rule=item.selection_rule,
                public_product_ids=item.public_product_ids,
                notes=item.notes,
            )
        )
    return PublicFailureAnalysis(
        run_id=report.run_id,
        minimum_slice_size=minimum_slice_size,
        slices=slices,
        examples=examples,
    )


def build_public_evidence(
    report: EvaluationReport,
    run: PublicRunSummary,
    queries: QueryStore,
    *,
    minimum_slice_size: int,
) -> PublicEvidenceEnvelope:
    """Project a held-out report; never infer unavailable baseline measurements."""

    if report.split.casefold() != "test":
        raise ValueError("public verified evidence must come from the held-out test report")
    if minimum_slice_size < 1:
        raise ValueError("minimum_slice_size must be positive")
    interval = _primary_interval(report)
    strongest_id = report.primary_metric.strongest_baseline_id
    models = _public_models(report)
    baseline_name = next(model.display_name for model in models if model.model_id == strongest_id)
    evaluation = PublicEvaluationEvidence(
        report_id=report.report_id,
        run_id=report.run_id,
        candidate_model_id=report.candidate_model_id,
        strongest_baseline_model_id=strongest_id,
        release_status="passed" if report.release_gate_results.passed else "failed",
        primary_metric=PublicMetricValue(
            metric="graded_ndcg@10",
            display_name="Graded nDCG@10",
            value=report.primary_metric.candidate_value,
        ),
        strongest_baseline=PublicMetricValue(
            metric="graded_ndcg@10",
            display_name=baseline_name,
            value=report.primary_metric.strongest_baseline_value,
        ),
        delta=PublicMetricValue(
            metric="graded_ndcg@10",
            display_name="Candidate minus strongest unchanged baseline",
            value=report.primary_metric.candidate_minus_baseline,
            interval=interval,
        ),
        held_out_query_count=report.query_count,
        bootstrap_resamples=report.bootstrap_resamples,
        bootstrap_seed=report.bootstrap_seed,
        test_access_count=report.test_access_count,
        excluded_query_count=report.excluded_query_count,
        exclusion_note=(
            f"The report records {report.excluded_query_count} queries excluded from the "
            "primary metric under project_graded_v1."
        ),
        models=models,
        secondary_metrics=_secondary_comparisons(report),
    )
    return PublicEvidenceEnvelope(
        run=run,
        evaluation=evaluation,
        failure_analysis=_public_failure_analysis(
            report,
            queries,
            minimum_slice_size=minimum_slice_size,
        ),
    )


def build_validation_public_evidence(
    run: PublicValidationRunSummary,
    *,
    evidence_id: str,
    validation_query_count: int,
    excluded_query_count: int,
    models: list[PublicModelMetricRow],
    selection_note: str,
    failure_analysis_reason: str,
) -> PublicEvidenceEnvelope:
    """Build an explicitly non-held-out baseline bootstrap envelope."""

    selected = next((model for model in models if model.model_id == run.selected_model_id), None)
    if selected is None:
        raise ValueError("validation-selected model is absent from model metrics")
    evaluation = PublicValidationEvaluation(
        evidence_id=evidence_id,
        run_id=run.run_id,
        selected_model_id=run.selected_model_id,
        primary_metric=PublicMetricValue(
            metric="graded_ndcg@10",
            display_name="Validation graded nDCG@10",
            value=selected.graded_ndcg_at_10,
        ),
        validation_query_count=validation_query_count,
        excluded_query_count=excluded_query_count,
        models=models,
        selection_note=selection_note,
    )
    return PublicEvidenceEnvelope(
        evidence_mode="validation_only",
        run=run,
        evaluation=evaluation,
        failure_analysis=PublicValidationFailureAnalysis(
            run_id=run.run_id,
            reason=failure_analysis_reason,
        ),
    )


def write_public_evidence(evidence: PublicEvidenceEnvelope, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


__all__ = [
    "build_public_evidence",
    "build_validation_public_evidence",
    "public_run_intervals",
    "public_run_metrics",
    "write_public_evidence",
]
