from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
import pytest

from search_rank.baselines import cross_encoder
from search_rank.baselines.common import ScoredProduct
from search_rank.training.mine_hard_examples import mine_hard_examples


class _RecordingCrossEncoder:
    def __init__(self, scores_by_text: dict[str, float]) -> None:
        self.scores_by_text = scores_by_text
        self.calls: list[list[tuple[str, str]]] = []
        self.options: list[dict[str, Any]] = []

    def predict(self, sentences: list[tuple[str, str]], **kwargs: Any) -> np.ndarray:
        self.calls.append(list(sentences))
        self.options.append(kwargs)
        return np.asarray(
            [[self.scores_by_text[text]] for _, text in sentences],
            dtype=float,
        )


class _Clock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def _candidate_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("q2", "second", "p5", 5, "Irrelevant", "text-5"),
            ("q1", "first", "p3", 3, "Substitute", "text-3"),
            ("q1", "first", "p1", 1, "Exact", "text-1"),
            ("q3", "third", "p7", 7, "Complement", "text-7"),
            ("q2", "second", "p2", 2, "Exact", "text-2"),
            ("q1", "first", "p2", 2, "Complement", "text-2"),
            ("q3", "third", "p6", 6, "Exact", "text-6"),
        ],
        columns=[
            "query_id",
            "query",
            "product_id",
            "source_index",
            "esci_label",
            "text_enriched_v1",
        ],
        index=[70, 10, 40, 90, 20, 80, 30],
    )


def test_cross_encoder_chunking_preserves_ranking_scores_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _candidate_frame()
    scores = {
        "text-1": 0.9,
        "text-2": 0.4,
        "text-3": 0.4,
        "text-5": 0.4,
        "text-6": 0.8,
        "text-7": 0.2,
    }

    unchunked = _RecordingCrossEncoder(scores)
    monkeypatch.setattr(cross_encoder, "_PREDICTION_CHUNK_SIZE", len(frame) + 1)
    monkeypatch.setattr(cross_encoder.time, "perf_counter", _Clock([0.0, 3.0]))
    expected = cross_encoder.rank_cross_encoder(
        frame,
        model=unchunked,  # type: ignore[arg-type]
        model_id="fixture-cross-encoder",
        batch_size=2,
    )

    chunked = _RecordingCrossEncoder(scores)
    monkeypatch.setattr(cross_encoder, "_PREDICTION_CHUNK_SIZE", 3)
    monkeypatch.setattr(
        cross_encoder.time,
        "perf_counter",
        _Clock([0.0, 1.0, 1.0, 2.0, 2.0, 3.0]),
    )
    actual = cross_encoder.rank_cross_encoder(
        frame,
        model=chunked,  # type: ignore[arg-type]
        model_id="fixture-cross-encoder",
        batch_size=2,
    )

    assert actual == expected
    assert [len(call) for call in chunked.calls] == [3, 3, 1]
    assert [pair for call in chunked.calls for pair in call] == unchunked.calls[0]
    assert all(
        options
        == {
            "batch_size": 2,
            "show_progress_bar": False,
            "convert_to_numpy": True,
        }
        for options in chunked.options
    )
    assert [record.query_id for record in actual] == ["q1", "q1", "q1", "q2", "q2", "q3", "q3"]
    assert all(record.latency_ms == pytest.approx(3000 / len(frame)) for record in actual)


def test_cross_encoder_rejects_a_chunk_with_the_wrong_prediction_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ShortPrediction:
        def predict(self, sentences: list[tuple[str, str]], **_: Any) -> np.ndarray:
            return np.zeros(max(len(sentences) - 1, 0), dtype=float)

    monkeypatch.setattr(cross_encoder, "_PREDICTION_CHUNK_SIZE", 2)
    monkeypatch.setattr(cross_encoder.time, "perf_counter", _Clock([0.0, 1.0]))

    with pytest.raises(ValueError, match="prediction count"):
        cross_encoder.rank_cross_encoder(
            _candidate_frame(),
            model=_ShortPrediction(),  # type: ignore[arg-type]
            model_id="fixture-cross-encoder",
        )


def _legacy_mine_hard_examples(
    training_frame: pd.DataFrame,
    baseline_rankings: Iterable[ScoredProduct],
) -> pd.DataFrame:
    candidates = training_frame[["query_id", "product_id", "esci_label"]].copy()
    candidates["query_id"] = candidates["query_id"].astype(str)
    candidates["product_id"] = candidates["product_id"].astype(str)
    gains = {"Exact": 3, "Substitute": 2, "Complement": 1, "Irrelevant": 0}
    candidates["grade"] = candidates["esci_label"].map(gains)
    scores = pd.DataFrame(
        [
            {
                "query_id": record.query_id,
                "product_id": record.product_id,
                "source_baseline": record.model_id,
                "baseline_score": record.score,
            }
            for record in baseline_rankings
        ]
    )
    joined = scores.merge(candidates, on=["query_id", "product_id"], validate="many_to_one")
    hard_rows: list[dict[str, object]] = []
    for (query_id, baseline_id), group in joined.groupby(
        ["query_id", "source_baseline"], sort=True
    ):
        rows = group.sort_values(
            ["baseline_score", "product_id"],
            ascending=[False, True],
            kind="mergesort",
        ).to_dict(orient="records")
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


def test_memory_bounded_mining_matches_the_previous_dataframe_semantics() -> None:
    frame = pd.DataFrame(
        [
            ("q2", "d", "Complement", "train"),
            ("q1", "c", "Irrelevant", "train"),
            ("q1", "a", "Exact", "train"),
            ("q2", "b", "Substitute", "train"),
            ("q1", "b", "Substitute", "train"),
            ("q2", "a", "Exact", "train"),
            ("q1", "d", "Complement", "train"),
            ("q2", "c", "Irrelevant", "train"),
        ],
        columns=["query_id", "product_id", "esci_label", "project_split"],
    )
    records = [
        ScoredProduct("q2", "query 2", "a", "z-model", 0.1, 4, 0, "Exact", 0),
        ScoredProduct("q1", "query 1", "d", "a-model", 0.7, 2, 0, "Complement", 0),
        ScoredProduct("q1", "query 1", "c", "z-model", 0.9, 1, 0, "Irrelevant", 0),
        ScoredProduct("q2", "query 2", "c", "z-model", 0.8, 1, 0, "Irrelevant", 0),
        ScoredProduct("q1", "query 1", "a", "a-model", 0.2, 4, 0, "Exact", 0),
        ScoredProduct("q2", "query 2", "b", "z-model", 0.4, 3, 0, "Substitute", 0),
        ScoredProduct("q1", "query 1", "b", "z-model", 0.6, 3, 0, "Substitute", 0),
        ScoredProduct("q1", "query 1", "b", "a-model", 0.7, 1, 0, "Substitute", 0),
        ScoredProduct("q2", "query 2", "d", "z-model", 0.6, 2, 0, "Complement", 0),
        ScoredProduct("q1", "query 1", "d", "z-model", 0.7, 2, 0, "Complement", 0),
        ScoredProduct("q1", "query 1", "a", "z-model", 0.1, 4, 0, "Exact", 0),
        ScoredProduct("q1", "query 1", "c", "a-model", 0.9, 3, 0, "Irrelevant", 0),
    ]

    expected = _legacy_mine_hard_examples(frame, records)
    actual = mine_hard_examples(frame, (record for record in records))

    pd.testing.assert_frame_equal(actual, expected)
