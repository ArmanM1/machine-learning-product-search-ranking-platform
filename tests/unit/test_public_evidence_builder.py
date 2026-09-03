from __future__ import annotations

from datetime import UTC, datetime

import pytest

from search_rank.evaluation.gates import ReleaseGateInputs, evaluate_release_gate
from search_rank.evaluation.latency import summarize_latency
from search_rank.evaluation.report import build_primary_metric
from search_rank.schemas.api import (
    PublicEvaluationProvenance,
    PublicModelMetricRow,
    PublicRunSummary,
    PublicTrainingProvenance,
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
from search_rank.serving.dependencies import ServiceState
from search_rank.serving.public_evidence import (
    build_public_evidence,
    build_validation_public_evidence,
    public_run_intervals,
    public_run_metrics,
)
from search_rank.serving.query_store import CuratedProduct, CuratedQuery, QueryStore

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
BASELINE_ID = "bm25-v1-text_enriched_v1"
CANDIDATE_ID = "candidate-v1"
GIT_SHA = "a" * 40


def _heldout_examples() -> list[ExampleResult]:
    examples = [
        ExampleResult(
            query_id=f"q{index}",
            category="loss",
            baseline_metric=0.70,
            candidate_metric=0.60 - index * 0.001,
            delta=-0.10 - index * 0.001,
            selection_rule="largest negative primary-metric delta",
            public_product_ids=["p1", "p2"] if index == 1 else [],
        )
        for index in range(1, 6)
    ]
    examples.extend(
        ExampleResult(
            query_id=f"q{index}",
            category="win",
            baseline_metric=0.60,
            candidate_metric=0.70 + index * 0.001,
            delta=0.10 + index * 0.001,
            selection_rule="largest positive primary-metric delta",
        )
        for index in range(6, 11)
    )
    examples.extend(
        ExampleResult(
            query_id=f"q{index}",
            category="tie_or_uncertain",
            baseline_metric=0.65,
            candidate_metric=0.65,
            delta=0,
            selection_rule="near-zero primary-metric delta",
        )
        for index in range(11, 14)
    )
    examples.extend(
        [
            ExampleResult(
                query_id="q14",
                category="lexical_preferred",
                baseline_metric=0.75,
                candidate_metric=0.60,
                delta=-0.15,
                selection_rule="lexical baseline outscored candidate",
            ),
            ExampleResult(
                query_id="q15",
                category="complement_exact_confusion",
                baseline_metric=0.70,
                candidate_metric=0.55,
                delta=-0.15,
                selection_rule="automatically detected Complement-versus-Exact inversion",
            ),
        ]
    )
    return examples


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
        example_results=_heldout_examples(),
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
        split_manifest_hash=SHA_C,
        git_sha=GIT_SHA,
        model_artifact_checksum=SHA_B,
        dataset_name="Amazon Shopping Queries ESCI",
        dataset_version="small-v1",
        locale="us",
        base_model_id="cross-encoder/model",
        base_model_revision="233e41b",
        training_strategy="mixed difficult and seeded-random examples",
        training_provenance=PublicTrainingProvenance(
            trial_selection_id="trial-selection-" + "1" * 20,
            trial_selection_sha256=SHA_A,
            run_id="training-run-1",
            run_manifest_sha256=SHA_B,
            selected_model_id=CANDIDATE_ID,
            selected_model_artifact_checksum=SHA_A,
            config_hash=SHA_A,
            git_sha=GIT_SHA,
            image_digest=SHA_A,
            hardware_class="ml.g4dn.xlarge",
            accelerator="gpu",
            region="us-east-1",
            runtime_seconds=60,
            estimated_cost_usd=0.80,
            actual_cost_usd=None,
            cost_evidence="Training upper bound; final charge not reconciled.",
        ),
        evaluation_provenance=PublicEvaluationProvenance(
            candidate_model_id=CANDIDATE_ID,
            candidate_model_artifact_checksum=SHA_A,
            evaluation_config_hash=SHA_B,
            git_sha=GIT_SHA,
            image_digest=SHA_B,
            hardware_class="ml.m5.xlarge",
            region="us-east-1",
            clean_execution_count=2,
            runtime_seconds=10,
            runtime_basis="processing_job_wall_clock_sum",
            estimated_cost_usd=0.20,
            actual_cost_usd=None,
            cost_evidence="Processing upper bound; final charge not reconciled.",
        ),
        metrics=public_run_metrics(report),
        intervals=public_run_intervals(report),
        test_access_count=1,
        limitations=["Reranks only supplied candidates."],
        prohibited_claims=["No claim of shopper impact."],
        reproduction_command="search-rank reproduce --run-id run-1",
    )


def _queries() -> QueryStore:
    return QueryStore(
        [
            CuratedQuery(
                f"q{index}",
                "travel mug" if index == 1 else f"fixture query {index}",
                (
                    CuratedProduct(
                        "p1" if index == 1 else f"q{index}-p1",
                        "Travel mug" if index == 1 else f"Product {index}",
                        "Travel mug" if index == 1 else f"Product {index}",
                        "Exact",
                    ),
                    CuratedProduct(
                        "p2" if index == 1 else f"q{index}-p2",
                        "Mug rack" if index == 1 else f"Alternative {index}",
                        "Mug rack" if index == 1 else f"Alternative {index}",
                        "Complement",
                    ),
                ),
            )
            for index in range(1, 16)
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
    manifest = {
        "dataset_manifest_hash": SHA_B,
        "split_manifest_hash": SHA_C,
        "git_sha": GIT_SHA,
        "schema_version": "1.0.0",
        "release_id": report.report_id,
        "evidence_mode": "verified",
        "promoted_model_id": BASELINE_ID,
        "evaluation_report_id": report.report_id,
        "artifact_checksums": {
            "candidate-model-artifact.json": SHA_A,
            "evaluation-report.json": SHA_A,
            "evaluation-provenance.json": SHA_A,
            "curated-queries.json": SHA_A,
            "public-evidence.json": SHA_A,
            "LICENSE": SHA_A,
            "NOTICE": SHA_A,
        },
        "provenance": {
            "training": evidence.run.training_provenance.model_dump(mode="json"),
            "evaluation": evidence.run.evaluation_provenance.model_dump(mode="json"),
        },
        "models": [
            {
                "model_id": BASELINE_ID,
                "kind": "bm25",
                "text_template": "enriched_v1",
                "artifact_checksum": SHA_B,
                "public_summary": {
                    "model_id": BASELINE_ID,
                    "display_name": "BM25 lexical baseline",
                    "kind": "bm25",
                    "base_model_id": None,
                    "artifact_checksum": SHA_B,
                    "evaluation_report_id": report.report_id,
                    "promoted_at": "2026-09-02T00:00:00Z",
                    "limitations_url": "/methodology#limitations",
                },
            },
            {
                "model_id": CANDIDATE_ID,
                "kind": "fine_tuned",
                "checkpoint": "models/candidate",
                "text_template": "enriched_v1",
                "artifact_checksum": SHA_A,
                "batch_size": 32,
                "public_summary": {
                    "model_id": CANDIDATE_ID,
                    "display_name": "Fine-tuned candidate",
                    "kind": "fine_tuned",
                    "base_model_id": "cross-encoder/model",
                    "artifact_checksum": SHA_A,
                    "evaluation_report_id": report.report_id,
                    "promoted_at": None,
                    "limitations_url": "/methodology#limitations",
                },
            },
        ],
    }
    ServiceState._validate_evidence_binding(evidence, manifest)

    falsely_promoted = {**manifest, "promoted_model_id": CANDIDATE_ID}
    with pytest.raises(
        ValueError,
        match=r"model checksum differs|release decision differs|promoted model summary",
    ):
        ServiceState._validate_evidence_binding(evidence, falsely_promoted)

    conflated = {
        **manifest,
        "provenance": {
            **manifest["provenance"],
            "training": {
                **evidence.run.training_provenance.model_dump(mode="json"),
                "hardware_class": "ml.m5.xlarge",
            },
        },
    }
    with pytest.raises(
        ValueError,
        match=r"execution provenance differs|training hardware and accelerator do not match",
    ):
        ServiceState._validate_evidence_binding(evidence, conflated)


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
        split_manifest_hash=SHA_C,
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
