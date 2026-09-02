from __future__ import annotations

from datetime import UTC, datetime

import pytest

from search_rank.evaluation.gates import ReleaseGateInputs, evaluate_release_gate
from search_rank.evaluation.latency import summarize_latency
from search_rank.evaluation.report import build_primary_metric
from search_rank.schemas.api import (
    PublicModelMetricRow,
    PublicRunSummary,
    PublicValidationRunMetrics,
    PublicValidationRunSummary,
)
from search_rank.schemas.evaluation import (
    CostEvidence,
    EvaluationReport,
    ExampleResult,
    MemoryResult,
    MetricResult,
    PairedDifference,
    RuntimeResult,
)
from search_rank.serving.public_evidence import (
    build_public_evidence,
    build_validation_public_evidence,
    public_run_intervals,
    public_run_metrics,
)
from search_rank.serving.query_store import CuratedProduct, CuratedQuery, QueryStore

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
BASELINE_ID = "bm25-v1-text_enriched_v1"
CANDIDATE_ID = "candidate-v1"


def _report() -> EvaluationReport:
    gate = evaluate_release_gate(
        ReleaseGateInputs(
            candidate_model_id=CANDIDATE_ID,
            strongest_baseline_model_id=BASELINE_ID,
            candidate_ndcg_at_10=0.69,
            baseline_ndcg_at_10=0.70,
            difference_ci_lower=-0.03,
            difference_ci_upper=0.01,
            confidence_level=0.95,
            relevance_mapping_version="project_graded_v1",
            resampling_unit="query",
            bootstrap_seed=42,
            bootstrap_resamples=10_000,
            query_count=100,
            excluded_query_count=2,
            test_access_count=1,
            clean_run_metric_values=(0.69, 0.69),
            candidate_lists_aligned=True,
            configuration_frozen=True,
            clean_runs_match_artifacts=True,
        )
    )
    return EvaluationReport(
        schema_version="1.0.0",
        report_id="report-1",
        run_id="run-1",
        candidate_model_id=CANDIDATE_ID,
        baseline_model_ids=[BASELINE_ID],
        split="test",
        test_access_count=1,
        query_count=100,
        excluded_query_count=2,
        metric_definition_version="project_graded_v1",
        primary_metric=build_primary_metric(0.69, {BASELINE_ID: 0.70}),
        secondary_metrics={
            "exact_mrr@10": MetricResult(metric_name="exact_mrr@10", value=0.61, query_count=102)
        },
        system_metrics={
            CANDIDATE_ID: {
                "graded_ndcg@10": MetricResult(
                    metric_name="graded_ndcg@10", value=0.69, query_count=100
                ),
                "exact_mrr@10": MetricResult(
                    metric_name="exact_mrr@10", value=0.61, query_count=102
                ),
            },
            BASELINE_ID: {
                "graded_ndcg@10": MetricResult(
                    metric_name="graded_ndcg@10", value=0.70, query_count=100
                ),
                "exact_mrr@10": MetricResult(
                    metric_name="exact_mrr@10", value=0.65, query_count=102
                ),
            },
        },
        paired_differences=[
            PairedDifference(
                metric_name="graded_ndcg@10",
                candidate_model_id=CANDIDATE_ID,
                baseline_model_id=BASELINE_ID,
                point_estimate=-0.01,
                ci_lower=-0.03,
                ci_upper=0.01,
                confidence_level=0.95,
                query_count=100,
                excluded_query_count=2,
                bootstrap_seed=42,
                bootstrap_resamples=10_000,
            )
        ],
        bootstrap_method="paired_nonparametric_percentile",
        bootstrap_seed=42,
        bootstrap_resamples=10_000,
        confidence_level=0.95,
        slice_results=[],
        example_results=[
            ExampleResult(
                query_id="q1",
                category="loss",
                baseline_metric=0.70,
                candidate_metric=0.60,
                delta=-0.10,
                selection_rule="largest negative primary-metric delta",
                public_product_ids=["p1", "p2"],
            )
        ],
        latency_results=[
            summarize_latency(
                [10],
                phase="model_inference",
                candidate_count=2,
                concurrency=1,
                lambda_memory_mb=2048,
                architecture="arm64",
                region="us-east-1",
                reserved_concurrency=2,
                model_revision=CANDIDATE_ID,
            ),
            summarize_latency(
                [2],
                phase="model_inference",
                candidate_count=2,
                concurrency=1,
                lambda_memory_mb=None,
                architecture="arm64",
                region="us-east-1",
                reserved_concurrency=None,
                model_revision=BASELINE_ID,
            ),
        ],
        memory_results=MemoryResult(
            peak_resident_memory_mb=500,
            model_artifact_size_bytes=1_000,
            measurement_method="resource.getrusage",
        ),
        training_runtime=RuntimeResult(duration_seconds=60, hardware="gpu", measured=True),
        evaluation_runtime=RuntimeResult(duration_seconds=10, hardware="cpu", measured=True),
        cost_evidence=CostEvidence(
            estimated_cost_usd=1.0,
            actual_cost_usd=None,
            source="billing reconciliation pending",
        ),
        release_gate_results=gate,
        limitations=["Candidate lists are supplied; this is not full-catalog retrieval."],
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def _run(report: EvaluationReport) -> PublicRunSummary:
    return PublicRunSummary(
        run_id=report.run_id,
        config_hash=SHA_A,
        dataset_manifest_hash=SHA_B,
        git_sha="abcdef1",
        image_digest=SHA_A,
        model_artifact_checksum=SHA_B,
        dataset_name="Amazon Shopping Queries ESCI",
        dataset_version="small-v1",
        locale="us",
        base_model_id="cross-encoder/model",
        base_model_revision="233e41b",
        training_strategy="mixed difficult and seeded-random examples",
        hardware_class="ml.g4dn.xlarge",
        region="us-east-1",
        metrics=public_run_metrics(report),
        intervals=public_run_intervals(report),
        duration_seconds=70,
        actual_cost_usd=None,
        cost_evidence="Billing reconciliation is pending.",
        test_access_count=1,
        limitations=["Reranks only supplied candidates."],
        prohibited_claims=["No claim of shopper impact."],
        reproduction_command="search-rank reproduce --run-id run-1",
    )


def _queries() -> QueryStore:
    return QueryStore(
        [
            CuratedQuery(
                "q1",
                "travel mug",
                (
                    CuratedProduct("p1", "Travel mug", "Travel mug", "Exact"),
                    CuratedProduct("p2", "Mug rack", "Mug rack", "Complement"),
                ),
            )
        ]
    )


def test_builder_projects_only_measured_values_and_preserves_negative_result() -> None:
    report = _report()
    evidence = build_public_evidence(report, _run(report), _queries(), minimum_slice_size=30)

    assert evidence.evaluation.release_status == "failed"
    assert len(evidence.evaluation.secondary_metrics) == 1
    assert evidence.evaluation.secondary_metrics[0].metric == "exact_mrr@10"
    candidate = next(
        model for model in evidence.evaluation.models if model.model_id == CANDIDATE_ID
    )
    baseline = next(model for model in evidence.evaluation.models if model.model_id == BASELINE_ID)
    assert candidate.exact_mrr_at_10 == 0.61
    assert candidate.p95_inference_latency_ms == 10
    assert baseline.exact_mrr_at_10 == 0.65
    assert baseline.p95_inference_latency_ms == 2
    assert evidence.failure_analysis.examples[0].query.query == "travel mug"


def test_builder_refuses_non_heldout_evidence() -> None:
    report = _report().model_copy(update={"split": "validation"})
    with pytest.raises(ValueError, match="held-out test"):
        build_public_evidence(report, _run(report), _queries(), minimum_slice_size=30)


def test_validation_builder_is_explicitly_non_heldout() -> None:
    model = PublicModelMetricRow(
        model_id=BASELINE_ID,
        display_name="BM25 lexical baseline",
        kind="bm25",
        graded_ndcg_at_10=0.70,
        exact_mrr_at_10=0.65,
        p95_inference_latency_ms=2,
    )
    run = PublicValidationRunSummary(
        run_id="baseline-run-1",
        selected_model_id=BASELINE_ID,
        config_hash=SHA_A,
        dataset_manifest_hash=SHA_B,
        git_sha="abcdef1",
        image_digest=SHA_A,
        model_artifact_checksum=SHA_B,
        dataset_name="Amazon Shopping Queries ESCI",
        dataset_version="small-v1",
        locale="us",
        base_model_id=None,
        hardware_class="local-cpu",
        region="us-east-1",
        metrics=PublicValidationRunMetrics(selected_model_graded_ndcg_at_10=0.70),
        duration_seconds=5,
        actual_cost_usd=0,
        cost_evidence="Local validation execution; no AWS workload charge.",
        validation_only_notice="Baseline selected on validation before held-out access.",
        limitations=["This evidence is validation-only."],
        prohibited_claims=["No held-out ranking-improvement claim is allowed."],
        reproduction_command="search-rank baseline run --config baseline.yaml",
    )
    evidence = build_validation_public_evidence(
        run,
        evidence_id="baseline-summary-1",
        validation_query_count=100,
        excluded_query_count=2,
        models=[model],
        selection_note="Selected by highest validation graded nDCG@10 with deterministic ties.",
        failure_analysis_reason="Held-out failure analysis has not been performed.",
    )

    assert evidence.evidence_mode == "validation_only"
    assert evidence.run.test_access_count == 0
    assert evidence.evaluation.test_access_count == 0
    assert evidence.failure_analysis.status == "not_performed"
