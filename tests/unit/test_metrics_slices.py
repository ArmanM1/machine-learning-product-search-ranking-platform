from __future__ import annotations

import pytest

from search_rank.evaluation.slices import (
    CandidateSliceFeatures,
    assign_predeclared_slices,
    evaluate_slices,
    query_token_length_bin,
    select_slice_highlights,
)


def test_frozen_slice_bin_assignment() -> None:
    candidates = [
        CandidateSliceFeatures(
            title="Red shoes",
            relevance="Exact",
            brand="Acme",
            bullet_point="Lightweight",
            description="",
            product_source="catalog-a",
        ),
        CandidateSliceFeatures(
            title="Blue boots",
            relevance="Irrelevant",
            product_source="catalog-a",
        ),
    ]
    assert assign_predeclared_slices("red running shoes", candidates) == {
        "query_token_length": "3_to_4_tokens",
        "candidate_label_composition": "exact_present",
        "brand_presence": "brand_partial",
        "product_text_completeness": "text_partial_50_to_lt_75pct",
        "query_title_lexical_overlap": "overlap_medium_le_2_3",
        "product_source": "source:catalog-a",
    }
    assert query_token_length_bin("one") == "1_token"
    assert query_token_length_bin("one two") == "2_tokens"
    assert query_token_length_bin("one two three four five") == "5_plus_tokens"


def test_slice_comparisons_are_paired_and_flag_small_samples() -> None:
    candidate = {"q1": 0.8, "q2": 0.7, "q3": 0.5}
    baseline = {"q1": 0.7, "q2": 0.6, "q3": 0.6}
    assignments = {
        "q1": {"query_token_length": "short"},
        "q2": {"query_token_length": "short"},
        "q3": {"query_token_length": "long"},
    }
    results = evaluate_slices(
        candidate,
        baseline,
        assignments,
        n_resamples=100,
        seed=9,
        minimum_query_count=2,
    )
    by_name = {result.slice_name: result for result in results}
    assert by_name["short"].adequate_sample_size is True
    assert by_name["short"].point_estimate == pytest.approx(0.1)
    assert by_name["long"].adequate_sample_size is False
    highlights = select_slice_highlights(results)
    assert highlights.strongest_improvement is by_name["short"]
    assert highlights.inadequate_sample_slices == (by_name["long"],)
