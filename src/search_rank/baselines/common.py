"""Shared ranking-result contract and deterministic serialization."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScoredProduct:
    query_id: str
    query: str
    product_id: str
    model_id: str
    score: float
    rank: int
    source_index: int
    esci_label: str
    latency_ms: float


def write_rankings(path: str | Path, records: list[ScoredProduct]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), sort_keys=True, ensure_ascii=False) + "\n")
    return output


def read_rankings(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def records_from_scores(
    frame: Any,
    *,
    scores: list[float],
    model_id: str,
    latency_ms: float,
) -> list[ScoredProduct]:
    if len(frame) != len(scores):
        raise ValueError("candidate frame and score lengths differ")
    values = frame.copy()
    values["_score"] = scores
    values = values.sort_values(["_score", "product_id"], ascending=[False, True], kind="mergesort")
    per_item_latency = latency_ms / len(values) if len(values) else 0.0
    return [
        ScoredProduct(
            query_id=str(row["query_id"]),
            query=str(row["query"]),
            product_id=str(row["product_id"]),
            model_id=model_id,
            score=float(row["_score"]),
            rank=rank,
            source_index=int(row["source_index"]),
            esci_label=str(row["esci_label"]),
            latency_ms=per_item_latency,
        )
        for rank, row in enumerate(values.to_dict(orient="records"), start=1)
    ]
