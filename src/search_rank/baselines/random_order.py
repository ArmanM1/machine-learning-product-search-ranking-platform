"""Query-derived seeded-random diagnostic control."""

from __future__ import annotations

import hashlib
import time

import pandas as pd

from .common import ScoredProduct, records_from_scores


def _score(query_id: str, product_id: str, seed: int) -> float:
    value = int.from_bytes(
        hashlib.sha256(f"{seed}\0{query_id}\0{product_id}".encode()).digest()[:8], "big"
    )
    return value / 2**64


def rank_seeded_random(frame: pd.DataFrame, *, seed: int = 42) -> list[ScoredProduct]:
    records: list[ScoredProduct] = []
    for query_id, group in frame.groupby("query_id", sort=True):
        started = time.perf_counter()
        scores = [
            _score(str(query_id), str(product_id), seed) for product_id in group["product_id"]
        ]
        elapsed = (time.perf_counter() - started) * 1000
        records.extend(
            records_from_scores(
                group,
                scores=scores,
                model_id=f"seeded-random-v1-seed-{seed}",
                latency_ms=elapsed,
            )
        )
    return records
