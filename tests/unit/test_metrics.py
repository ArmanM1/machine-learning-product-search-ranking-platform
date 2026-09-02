from __future__ import annotations

import math

import pytest

from search_rank.evaluation.metrics import (
    RankingAlignmentError,
    aggregate_query_metrics,
    dcg_at_k,
    exact_mrr_at_k,
    exact_top_1_rate,
    gain_for,
    ndcg_at_k,
    pairwise_ordinal_accuracy,
    rank_by_score,
    recall_exact_or_substitute_at_k,
    validate_ranking_alignment,
)

RANKED_LABELS = ["Substitute", "Exact", "Irrelevant", "Complement"]


def test_project_mapping_accepts_names_codes_and_gains() -> None:
    assert [gain_for(value) for value in ["E", "substitute", "C", "irrelevant"]] == [
        3,
        2,
        1,
        0,
    ]
    assert [gain_for(value) for value in [3, 2, 1, 0]] == [3, 2, 1, 0]
    with pytest.raises(ValueError, match="unknown relevance"):
        gain_for("relevant")


def test_hand_calculated_dcg_and_ndcg_fixture() -> None:
    # Ranked gains [2, 3, 0, 1]:
    # DCG = 2/log2(2) + 3/log2(3) + 0/log2(4) + 1/log2(5)
    # IDCG for [3, 2, 1, 0] = 3 + 2/log2(3) + 1/log2(4).
    assert dcg_at_k(RANKED_LABELS, 4) == pytest.approx(4.323465818787765)
    assert ndcg_at_k(RANKED_LABELS, 4) == pytest.approx(0.9079364505194771)


def test_hand_calculated_mrr_recall_pairwise_and_top1_fixture() -> None:
    assert exact_mrr_at_k(RANKED_LABELS, 10) == 0.5
    assert recall_exact_or_substitute_at_k(RANKED_LABELS, 1) == 0.5
    # Six unequal-grade pairs; four are correctly ordered.
    assert pairwise_ordinal_accuracy(RANKED_LABELS) == pytest.approx(4 / 6)
    assert exact_top_1_rate(RANKED_LABELS) == 0.0
    assert exact_top_1_rate(["Exact", "Irrelevant"]) == 1.0


def test_pairwise_score_tie_gets_half_credit() -> None:
    assert pairwise_ordinal_accuracy(["Exact", "Irrelevant"], [0.4, 0.4]) == 0.5


def test_zero_relevance_queries_are_excluded_from_ndcg_macro_average() -> None:
    assert ndcg_at_k(["Irrelevant", "Irrelevant"], 10) is None
    aggregate = aggregate_query_metrics(
        {
            "all-zero": ["Irrelevant", "Irrelevant"],
            "perfect": ["Exact", "Irrelevant"],
        }
    )
    assert aggregate.values["graded_ndcg@10"] == 1.0
    assert aggregate.metric_query_counts["graded_ndcg@10"] == 1
    assert aggregate.metric_excluded_query_counts["graded_ndcg@10"] == 1


def test_pairwise_has_explicit_degenerate_value() -> None:
    assert pairwise_ordinal_accuracy(["Exact", "Exact"]) is None


def test_equal_scores_break_ties_by_ascending_product_id() -> None:
    assert rank_by_score(["product-b", "product-a", "product-c"], [0.5, 0.5, 0.1]) == [
        1,
        0,
        2,
    ]


def test_candidate_alignment_accepts_different_orders_but_not_different_sets() -> None:
    validate_ranking_alignment({"q": ["a", "b"]}, {"q": ["b", "a"]})
    with pytest.raises(RankingAlignmentError, match="candidate-product mismatch"):
        validate_ranking_alignment({"q": ["a", "b"]}, {"q": ["a", "c"]})


def test_metrics_reject_nonfinite_scores() -> None:
    with pytest.raises(ValueError, match="finite"):
        rank_by_score(["a"], [math.inf])
