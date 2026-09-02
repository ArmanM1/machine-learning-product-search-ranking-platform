"""Dataset input-order diagnostic control."""

from __future__ import annotations

import time

import pandas as pd

from .common import ScoredProduct, records_from_scores


def rank_input_order(frame: pd.DataFrame) -> list[ScoredProduct]:
    records: list[ScoredProduct] = []
    for _, group in frame.groupby("query_id", sort=True):
        started = time.perf_counter()
        scores = [-float(value) for value in group["source_index"]]
        elapsed = (time.perf_counter() - started) * 1000
        records.extend(
            records_from_scores(group, scores=scores, model_id="input-order-v1", latency_ms=elapsed)
        )
    return records
