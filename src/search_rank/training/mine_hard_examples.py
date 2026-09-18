"""Training-only difficult-example mining from unchanged baselines."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TypeAlias

import pandas as pd

from search_rank.baselines.common import ScoredProduct
from search_rank.evaluation.metrics import gain_for

_ScoreRow: TypeAlias = tuple[float, str, int]
_HardRow: TypeAlias = tuple[str, str, str, int, int, int, str, float]


def _candidate_grades(training_frame: pd.DataFrame) -> dict[tuple[str, str], int]:
    grades: dict[tuple[str, str], int] = {}
    for query_id, product_id, label in zip(
        training_frame["query_id"],
        training_frame["product_id"],
        training_frame["esci_label"],
        strict=True,
    ):
        key = (str(query_id), str(product_id))
        if key in grades:
            raise ValueError("training frame contains duplicate query/product candidates")
        grades[key] = gain_for(label)
    return grades


def _group_scores(
    records: Iterable[ScoredProduct],
    candidate_grades: dict[tuple[str, str], int],
) -> dict[tuple[str, str], list[_ScoreRow]]:
    groups: dict[tuple[str, str], list[_ScoreRow]] = {}
    record_count = 0
    for record in records:
        record_count += 1
        candidate_key = (record.query_id, record.product_id)
        grade = candidate_grades.get(candidate_key)
        if grade is None:
            raise ValueError("baseline ranking contains non-training candidates")
        group_key = (record.query_id, record.model_id)
        groups.setdefault(group_key, []).append((float(record.score), record.product_id, grade))
    if record_count == 0:
        raise ValueError("baseline rankings are empty")
    return groups


def _score_order(row: _ScoreRow) -> tuple[bool, float, str]:
    score, product_id, _ = row
    return (math.isnan(score), -score if not math.isnan(score) else 0.0, product_id)


def mine_hard_examples(
    training_frame: pd.DataFrame,
    baseline_rankings: Iterable[ScoredProduct],
) -> pd.DataFrame:
    required = {"query_id", "product_id", "esci_label", "project_split"}
    missing = required - set(training_frame.columns)
    if missing:
        raise ValueError(f"training frame missing columns: {sorted(missing)}")
    unexpected = set(training_frame["project_split"].unique()) - {"train"}
    if unexpected:
        raise ValueError(
            f"hard-example mining accepts training rows only, got {sorted(unexpected)}"
        )

    candidate_grades = _candidate_grades(training_frame)
    score_groups = _group_scores(baseline_rankings, candidate_grades)

    hard_rows: list[_HardRow] = []
    for query_id, baseline_id in sorted(score_groups):
        rows = sorted(score_groups[(query_id, baseline_id)], key=_score_order)
        for lower_index, lower in enumerate(rows):
            lower_score, lower_product_id, lower_grade = lower
            higher = max(
                (item for item in rows[lower_index + 1 :] if item[2] > lower_grade),
                key=lambda item: (
                    item[2] - lower_grade,
                    lower_score - item[0],
                    item[1],
                ),
                default=None,
            )
            if higher is None:
                continue
            higher_score, higher_product_id, higher_grade = higher
            hard_rows.append(
                (
                    query_id,
                    lower_product_id,
                    higher_product_id,
                    lower_grade,
                    higher_grade,
                    higher_grade - lower_grade,
                    baseline_id,
                    lower_score - higher_score,
                )
            )
    columns = [
        "query_id",
        "lower_product_id",
        "higher_product_id",
        "lower_grade",
        "higher_grade",
        "grade_difference",
        "source_baseline",
        "score_margin",
    ]
    return pd.DataFrame(hard_rows, columns=columns).sort_values(
        ["query_id", "source_baseline", "score_margin", "lower_product_id"],
        ascending=[True, True, False, True],
        kind="mergesort",
        ignore_index=True,
    )
