"""Training-only difficult-example mining from unchanged baselines."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from search_rank.baselines.common import ScoredProduct
from search_rank.evaluation.metrics import gain_for


def _scores(records: Iterable[ScoredProduct]) -> pd.DataFrame:
    rows = [
        {
            "query_id": record.query_id,
            "product_id": record.product_id,
            "source_baseline": record.model_id,
            "baseline_score": record.score,
        }
        for record in records
    ]
    return pd.DataFrame(rows)


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

    candidates = training_frame[["query_id", "product_id", "esci_label"]].copy()
    candidates["query_id"] = candidates["query_id"].astype(str)
    candidates["product_id"] = candidates["product_id"].astype(str)
    candidates["grade"] = candidates["esci_label"].map(gain_for)
    scores = _scores(baseline_rankings)
    if scores.empty:
        raise ValueError("baseline rankings are empty")
    joined = scores.merge(candidates, on=["query_id", "product_id"], validate="many_to_one")
    if len(joined) != len(scores):
        raise ValueError("baseline ranking contains non-training candidates")

    hard_rows: list[dict[str, object]] = []
    for (query_id, baseline_id), group in joined.groupby(
        ["query_id", "source_baseline"], sort=True
    ):
        ordered = group.sort_values(
            ["baseline_score", "product_id"], ascending=[False, True], kind="mergesort"
        )
        rows = ordered.to_dict(orient="records")
        for lower_index, lower in enumerate(rows):
            better = [
                higher
                for higher in rows[lower_index + 1 :]
                if int(higher["grade"]) > int(lower["grade"])
            ]
            if not better:
                continue
            higher = max(
                better,
                key=lambda item: (
                    int(item["grade"]) - int(lower["grade"]),
                    float(lower["baseline_score"]) - float(item["baseline_score"]),
                    str(item["product_id"]),
                ),
            )
            hard_rows.append(
                {
                    "query_id": str(query_id),
                    "lower_product_id": str(lower["product_id"]),
                    "higher_product_id": str(higher["product_id"]),
                    "lower_grade": int(lower["grade"]),
                    "higher_grade": int(higher["grade"]),
                    "grade_difference": int(higher["grade"]) - int(lower["grade"]),
                    "source_baseline": str(baseline_id),
                    "score_margin": float(lower["baseline_score"])
                    - float(higher["baseline_score"]),
                }
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
