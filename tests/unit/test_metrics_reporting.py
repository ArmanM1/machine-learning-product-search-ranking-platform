from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError

from search_rank.baselines.common import ScoredProduct
from search_rank.cli import _candidate_universe_hash, _ranking_hash
from search_rank.evaluation.examples import ExampleCandidate, select_representative_examples
from search_rank.evaluation.gates import ReleaseGateInputs, evaluate_release_gate
from search_rank.evaluation.latency import summarize_latency
from search_rank.evaluation.report import (
    build_primary_metric,
    public_evaluation_outcome,
    select_strongest_baseline,
)
from search_rank.schemas.evaluation import (
    CostEvidence,
    EvaluationReport,
    MemoryResult,
    MetricResult,
    PairedDifference,
    RuntimeResult,
)


def test_ranking_hash_binds_order_but_not_input_iteration_order() -> None:
    first = [
        ScoredProduct("q1", "mug", "p1", "candidate", 0.9, 1, 0, "Exact", 1),
        ScoredProduct("q1", "mug", "p2", "candidate", 0.1, 2, 1, "Irrelevant", 1),
    ]
    swapped_ranks = [
        ScoredProduct("q1", "mug", "p1", "candidate", 0.9, 2, 0, "Exact", 1),
        ScoredProduct("q1", "mug", "p2", "candidate", 0.1, 1, 1, "Irrelevant", 1),
    ]

    assert _ranking_hash(first, include_scores=False) == _ranking_hash(
        list(reversed(first)), include_scores=False
    )
    assert _ranking_hash(first, include_scores=False) != _ranking_hash(
        swapped_ranks, include_scores=False
    )
    assert _candidate_universe_hash(first) == _candidate_universe_hash(swapped_ranks)


def test_candidate_universe_hash_rejects_duplicates_and_binds_membership() -> None:
    first = [
        ScoredProduct("q1", "mug", "p1", "candidate", 0.9, 1, 0, "Exact", 1),
        ScoredProduct("q1", "mug", "p2", "candidate", 0.1, 2, 1, "Irrelevant", 1),
    ]
    different = [
        first[0],
        ScoredProduct("q1", "mug", "p3", "candidate", 0.1, 2, 1, "Irrelevant", 1),
    ]

    assert _candidate_universe_hash(first) != _candidate_universe_hash(different)
    with pytest.raises(ValueError, match="duplicate query/product"):
        _candidate_universe_hash([first[0], first[0]])


def _complete_example_candidates() -> list[ExampleCandidate]:
    return [
        *[ExampleCandidate(f"win-{index}", 0.2, 0.8 - index * 0.01) for index in range(5)],
        *[
            ExampleCandidate(
                f"loss-{index}",
                0.8,
                0.2 + index * 0.01,
                lexical_preferred=index == 0,
                lexical_baseline_metric=0.9 if index == 0 else None,
                complement_exact_confusion=index == 1,
            )
            for index in range(5)
        ],
        *[ExampleCandidate(f"tie-{index}", 0.5, 0.5) for index in range(3)],
    ]


def test_latency_percentiles_use_disclosed_samples() -> None:
    result = summarize_latency(
        [10, 20, 30, 40, 50],
        phase="warm_end_to_end",
        candidate_count=40,
        concurrency=1,
        lambda_memory_mb=2048,
        architecture="arm64",
        region="us-east-1",
        reserved_concurrency=2,
        model_revision="rev-1",
    )
    assert result.sample_count == 5
    assert result.p50_ms == 30
    assert result.p95_ms == pytest.approx(48)
    assert result.p99_ms == pytest.approx(49.6)
    assert result.mean_ms == 30


def test_offline_latency_accepts_candidate_groups_above_public_api_cap() -> None:
    result = summarize_latency(
        [25, 30],
        phase="model_inference",
        candidate_count=70,
        concurrency=1,
        lambda_memory_mb=None,
        architecture="x86_64",
        region="local",
        reserved_concurrency=None,
        model_revision="offline-baseline",
    )
    assert result.candidate_count == 70


def test_example_selection_includes_wins_losses_ties_and_required_failures() -> None:
    candidates = [
        ExampleCandidate("win", 0.2, 0.8),
        ExampleCandidate("loss", 0.9, 0.2, lexical_preferred=True),
        ExampleCandidate("tie", 0.5, 0.5),
        ExampleCandidate("confusion", 0.8, 0.3, complement_exact_confusion=True),
    ]
    first = select_representative_examples(candidates, win_count=1, loss_count=1, uncertain_count=1)
    second = select_representative_examples(
        list(reversed(candidates)), win_count=1, loss_count=1, uncertain_count=1
    )
    assert first == second
    assert {item.category for item in first} == {
        "win",
        "loss",
        "tie_or_uncertain",
        "lexical_preferred",
        "complement_exact_confusion",
    }


def test_default_example_selection_is_complete_deterministic_and_uses_lexical_metric() -> None:
    candidates = _complete_example_candidates()
    first = select_representative_examples(candidates)
    second = select_representative_examples(list(reversed(candidates)))

    assert first == second
    assert [item.category for item in first].count("win") == 5
    assert [item.category for item in first].count("loss") == 5
    assert [item.category for item in first].count("tie_or_uncertain") == 3
    assert [item.category for item in first].count("lexical_preferred") == 1
    assert [item.category for item in first].count("complement_exact_confusion") == 1
    lexical = next(item for item in first if item.category == "lexical_preferred")
    assert lexical.baseline_metric == 0.9
    assert lexical.delta == pytest.approx(lexical.candidate_metric - 0.9)


def test_complete_example_selection_reports_every_unavailable_category() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"win required=5 available=1; loss required=5 available=0; "
            r"tie_or_uncertain required=3 available=0; "
            r"lexical_preferred required=1 available=0; "
            r"complement_exact_confusion required=1 available=0"
        ),
    ):
        select_representative_examples([ExampleCandidate("only-win", 0.0, 1.0)])


def test_exploratory_example_selection_may_be_partial() -> None:
    selected = select_representative_examples(
        [ExampleCandidate("only-win", 0.0, 1.0)], require_complete=False
    )
    assert [item.category for item in selected] == ["win"]


def test_strongest_baseline_selection_has_deterministic_tie_break() -> None:
    assert select_strongest_baseline({"z-model": 0.7, "a-model": 0.7}) == (
        "a-model",
        0.7,
    )
    primary = build_primary_metric(0.72, {"bm25": 0.65, "pretrained": 0.7})
    assert primary.strongest_baseline_id == "pretrained"
    assert primary.candidate_minus_baseline == pytest.approx(0.02)


def test_public_report_preserves_an_honest_negative_outcome() -> None:
    gate = evaluate_release_gate(
        ReleaseGateInputs(
            candidate_model_id="candidate",
            strongest_baseline_model_id="pretrained",
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
    report = EvaluationReport(
        schema_version="1.0.0",
        report_id="report-1",
        run_id="run-1",
        candidate_model_id="candidate",
        baseline_model_ids=["bm25", "pretrained"],
        split="test",
        test_access_count=1,
        query_count=100,
        excluded_query_count=2,
        metric_definition_version="project_graded_v1",
        primary_metric=build_primary_metric(0.69, {"bm25": 0.6, "pretrained": 0.7}),
        secondary_metrics={
            "exact_mrr@10": MetricResult(metric_name="exact_mrr@10", value=0.6, query_count=102)
        },
        paired_differences=[
            PairedDifference(
                metric_name="graded_ndcg@10",
                candidate_model_id="candidate",
                baseline_model_id="pretrained",
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
        example_results=select_representative_examples(_complete_example_candidates()),
        latency_results=[
            summarize_latency(
                [10],
                phase="warm_end_to_end",
                candidate_count=40,
                concurrency=1,
                lambda_memory_mb=2048,
                architecture="arm64",
                region="us-east-1",
                reserved_concurrency=2,
                model_revision="rev-1",
            )
        ],
        memory_results=MemoryResult(
            peak_resident_memory_mb=500,
            model_artifact_size_bytes=1_000,
            measurement_method="resource.getrusage",
        ),
        training_runtime=RuntimeResult(duration_seconds=60, hardware="cpu", measured=True),
        evaluation_runtime=RuntimeResult(duration_seconds=10, hardware="cpu", measured=True),
        cost_evidence=CostEvidence(estimated_cost_usd=0, actual_cost_usd=0, source="local"),
        release_gate_results=gate,
        limitations=["Candidate lists are supplied; this is not full-catalog retrieval."],
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    public = public_evaluation_outcome(report)
    release = cast(dict[str, object], public["release_gate_results"])
    assert public["result_kind"] == "negative_result"
    assert release["decision"] == "retain_baseline"
    assert release["negative_result_required"] is True


def test_heldout_report_rejects_missing_representative_example_categories() -> None:
    validation_report = EvaluationReport(
        schema_version="1.0.0",
        report_id="validation-report",
        run_id="validation-run",
        candidate_model_id="candidate",
        baseline_model_ids=["baseline"],
        split="validation",
        test_access_count=0,
        query_count=1,
        excluded_query_count=0,
        metric_definition_version="project_graded_v1",
        primary_metric=build_primary_metric(0.5, {"baseline": 0.5}),
        secondary_metrics={},
        paired_differences=[
            PairedDifference(
                metric_name="graded_ndcg@10",
                candidate_model_id="candidate",
                baseline_model_id="baseline",
                point_estimate=0.0,
                ci_lower=0.0,
                ci_upper=0.0,
                confidence_level=0.95,
                query_count=1,
                bootstrap_seed=42,
                bootstrap_resamples=10_000,
            )
        ],
        bootstrap_method="paired_nonparametric_percentile",
        bootstrap_seed=42,
        bootstrap_resamples=10_000,
        confidence_level=0.95,
        slice_results=[],
        example_results=[],
        latency_results=[],
        memory_results=MemoryResult(
            peak_resident_memory_mb=1,
            model_artifact_size_bytes=1,
            measurement_method="fixture",
        ),
        training_runtime=RuntimeResult(duration_seconds=1, hardware="fixture", measured=True),
        evaluation_runtime=RuntimeResult(duration_seconds=1, hardware="fixture", measured=True),
        cost_evidence=CostEvidence(estimated_cost_usd=0, actual_cost_usd=0, source="fixture"),
        release_gate_results=evaluate_release_gate(
            ReleaseGateInputs(
                candidate_model_id="candidate",
                strongest_baseline_model_id="baseline",
                candidate_ndcg_at_10=0.5,
                baseline_ndcg_at_10=0.5,
                difference_ci_lower=0.0,
                difference_ci_upper=0.0,
                confidence_level=0.95,
                relevance_mapping_version="project_graded_v1",
                resampling_unit="query",
                bootstrap_seed=42,
                bootstrap_resamples=10_000,
                query_count=1,
                excluded_query_count=0,
                test_access_count=1,
                clean_run_metric_values=(0.5, 0.5),
                candidate_lists_aligned=True,
                configuration_frozen=True,
                clean_runs_match_artifacts=True,
            )
        ),
        limitations=["fixture"],
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    payload = validation_report.model_dump(mode="json")
    payload.update(split="test", test_access_count=1)
    with pytest.raises(
        ValidationError,
        match=r"held-out representative-example requirements are incomplete: win required=5",
    ):
        EvaluationReport.model_validate(payload)
