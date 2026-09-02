from __future__ import annotations

import pytest

from search_rank.evaluation.bootstrap import (
    BootstrapAlignmentError,
    paired_bootstrap,
)


def test_paired_bootstrap_is_deterministic_and_insertion_order_independent() -> None:
    candidate = {"q2": 0.7, "q1": 0.9, "zero": None}
    baseline = {"q1": 0.8, "zero": None, "q2": 0.8}
    first = paired_bootstrap(candidate, baseline, n_resamples=500, seed=123)
    second = paired_bootstrap(
        dict(reversed(list(candidate.items()))),
        dict(reversed(list(baseline.items()))),
        n_resamples=500,
        seed=123,
    )
    assert first == second
    assert first.point_estimate == pytest.approx(0.0)
    assert first.query_count == 2
    assert first.excluded_query_count == 1
    assert first.excluded_query_ids == ("zero",)
    assert first.resampling_unit == "query"


def test_constant_query_differences_have_degenerate_exact_interval() -> None:
    result = paired_bootstrap(
        {"q1": 0.7, "q2": 0.8, "q3": 0.9},
        {"q1": 0.6, "q2": 0.7, "q3": 0.8},
        n_resamples=250,
        seed=42,
    )
    assert result.point_estimate == pytest.approx(0.1)
    assert result.ci_lower == pytest.approx(0.1)
    assert result.ci_upper == pytest.approx(0.1)


def test_bootstrap_requires_identical_query_groups() -> None:
    with pytest.raises(BootstrapAlignmentError, match="identical query IDs"):
        paired_bootstrap({"q1": 1.0}, {"q2": 1.0})


def test_bootstrap_refuses_all_excluded_queries() -> None:
    with pytest.raises(ValueError, match="no non-degenerate"):
        paired_bootstrap({"q": None}, {"q": None})
