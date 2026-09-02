"""Query-local BM25 competitive baseline."""

from __future__ import annotations

import re
import time

import pandas as pd
from rank_bm25 import BM25Okapi

from .common import ScoredProduct, records_from_scores

TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)
TOKENIZER_VERSION = "unicode_words_casefold_v1"


def tokenize(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value.casefold())


def bm25_model_id(
    *,
    text_column: str = "text_enriched_v1",
    k1: float = 1.5,
    b: float = 0.75,
) -> str:
    """Return the immutable identifier used by the query-local BM25 baseline."""

    return f"bm25-v1-{text_column}-{TOKENIZER_VERSION}-k1-{k1}-b-{b}"


def rank_bm25(
    frame: pd.DataFrame,
    *,
    text_column: str = "text_enriched_v1",
    k1: float = 1.5,
    b: float = 0.75,
) -> list[ScoredProduct]:
    if text_column not in frame:
        raise ValueError(f"missing BM25 text column: {text_column}")
    records: list[ScoredProduct] = []
    for _, group in frame.groupby("query_id", sort=True):
        started = time.perf_counter()
        corpus = [tokenize(str(text)) for text in group[text_column]]
        model = BM25Okapi(corpus, k1=k1, b=b)
        scores = [float(value) for value in model.get_scores(tokenize(str(group["query"].iloc[0])))]
        elapsed = (time.perf_counter() - started) * 1000
        records.extend(
            records_from_scores(
                group,
                scores=scores,
                model_id=bm25_model_id(text_column=text_column, k1=k1, b=b),
                latency_ms=elapsed,
            )
        )
    return records
