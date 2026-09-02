from __future__ import annotations

import pytest

from search_rank.evaluation.gates import (
    HeldoutAccessDenied,
    HeldoutEvaluationRequest,
    ReleaseGateInputs,
    authorize_heldout_evaluation,
    evaluate_release_gate,
)

HASH = "sha256:" + "a" * 64
EVALUATION_HASH = "sha256:" + "c" * 64
CHECKPOINT_HASH = "sha256:" + "b" * 64


def passing_inputs(**overrides: object) -> ReleaseGateInputs:
    values: dict[str, object] = {
        "candidate_model_id": "candidate-v1",
        "strongest_baseline_model_id": "pretrained-v1",
        "candidate_ndcg_at_10": 0.72,
        "baseline_ndcg_at_10": 0.70,
        "difference_ci_lower": 0.005,
        "difference_ci_upper": 0.035,
        "confidence_level": 0.95,
        "relevance_mapping_version": "project_graded_v1",
        "resampling_unit": "query",
        "bootstrap_seed": 42,
        "bootstrap_resamples": 10_000,
        "query_count": 200,
        "excluded_query_count": 3,
        "test_access_count": 1,
        "clean_run_metric_values": (0.72, 0.721),
        "candidate_lists_aligned": True,
        "configuration_frozen": True,
        "clean_runs_match_artifacts": True,
        "unexplained_slice_deltas": (-0.01, 0.03),
    }
    values.update(overrides)
    return ReleaseGateInputs(**values)  # type: ignore[arg-type]


def test_all_release_gates_promote_candidate() -> None:
    result = evaluate_release_gate(passing_inputs())
    assert result.passed is True
    assert result.decision == "promote_candidate"
    assert result.promoted_model_id == "candidate-v1"
    assert result.positive_claim_allowed is True
    assert result.negative_result_required is False


def test_negative_result_retains_baseline_and_stays_publishable() -> None:
    result = evaluate_release_gate(
        passing_inputs(
            candidate_ndcg_at_10=0.69,
            difference_ci_lower=-0.03,
            difference_ci_upper=0.01,
            clean_run_metric_values=(0.69, 0.69),
        )
    )
    assert result.passed is False
    assert result.decision == "retain_baseline"
    assert result.promoted_model_id == "pretrained-v1"
    assert result.positive_claim_allowed is False
    assert result.negative_result_required is True
    assert {check.name for check in result.checks if not check.passed} >= {
        "candidate_improves_primary_metric",
        "paired_interval_excludes_zero",
    }


@pytest.mark.parametrize(
    ("override", "failed_check"),
    [
        ({"bootstrap_seed": None}, "evaluation_disclosures"),
        ({"bootstrap_resamples": 2_000}, "final_bootstrap_resamples"),
        ({"resampling_unit": "row"}, "query_level_resampling"),
        ({"clean_run_metric_values": (0.72, 0.724)}, "clean_run_reproducibility"),
        ({"unexplained_slice_deltas": (-0.021,)}, "major_slice_regression"),
    ],
)
def test_gate_fails_closed(override: dict[str, object], failed_check: str) -> None:
    result = evaluate_release_gate(passing_inputs(**override))
    assert result.passed is False
    assert result.decision == "retain_baseline"
    assert failed_check in {check.name for check in result.checks if not check.passed}


def test_heldout_guard_requires_manual_environment_switch() -> None:
    request = HeldoutEvaluationRequest(
        HASH, EVALUATION_HASH, CHECKPOINT_HASH, ("bm25", "pretrained"), 2, 3
    )
    with pytest.raises(HeldoutAccessDenied, match="ALLOW_HELDOUT_EVAL"):
        authorize_heldout_evaluation(request, environ={})


def test_heldout_guard_returns_next_monotonic_access_count() -> None:
    request = HeldoutEvaluationRequest(
        HASH, EVALUATION_HASH, CHECKPOINT_HASH, ("bm25", "pretrained"), 2, 3
    )
    receipt = authorize_heldout_evaluation(request, environ={"ALLOW_HELDOUT_EVAL": "1"})
    assert receipt.authorized is True
    assert receipt.test_access_count == 3


def test_heldout_guard_rejects_skipped_counter() -> None:
    request = HeldoutEvaluationRequest(HASH, EVALUATION_HASH, CHECKPOINT_HASH, ("bm25",), 2, 4)
    with pytest.raises(HeldoutAccessDenied, match="monotonically by one"):
        authorize_heldout_evaluation(request, environ={"ALLOW_HELDOUT_EVAL": "1"})
