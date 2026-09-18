"""Unchanged pretrained cross-encoder competitive baseline."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd
import torch
import yaml
from sentence_transformers import CrossEncoder

from .common import ScoredProduct, records_from_scores

_PREDICTION_CHUNK_SIZE = 4096


class _CrossEncoderPredictor(Protocol):
    def predict(
        self,
        sentences: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> Any: ...


def choose_device(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_unchanged_model(config_path: str | Path, *, device: str = "auto") -> CrossEncoder:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if config.get("trust_remote_code") is not False:
        raise ValueError("model configuration must explicitly disable trust_remote_code")
    return cast(
        CrossEncoder,
        CrossEncoder(
            config["model_id"],
            revision=config["revision"],
            trust_remote_code=False,
            max_length=int(config["max_sequence_length"]),
            num_labels=1,
            device=choose_device(device),
        ),
    )


def rank_cross_encoder(
    frame: pd.DataFrame,
    *,
    model: CrossEncoder,
    model_id: str,
    text_column: str = "text_enriched_v1",
    batch_size: int = 32,
) -> list[ScoredProduct]:
    if text_column not in frame:
        raise ValueError(f"missing cross-encoder text column: {text_column}")
    row_count = len(frame)
    if row_count == 0:
        return []

    predictor = cast(_CrossEncoderPredictor, model)
    queries = frame["query"]
    texts = frame[text_column]
    scores = np.empty(row_count, dtype=float)
    elapsed_ms = 0.0
    for start in range(0, row_count, _PREDICTION_CHUNK_SIZE):
        stop = min(start + _PREDICTION_CHUNK_SIZE, row_count)
        pairs = [
            (str(query), str(text))
            for query, text in zip(
                queries.iloc[start:stop],
                texts.iloc[start:stop],
                strict=True,
            )
        ]
        started = time.perf_counter()
        predicted = predictor.predict(
            pairs,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        elapsed_ms += (time.perf_counter() - started) * 1000
        chunk_scores = np.asarray(predicted, dtype=float).reshape(-1)
        if len(chunk_scores) != stop - start:
            raise ValueError("cross-encoder prediction count differs from candidate rows")
        scores[start:stop] = chunk_scores

    records: list[ScoredProduct] = []
    for positions in frame.groupby("query_id", sort=True).indices.values():
        group = frame.iloc[positions]
        group_latency = elapsed_ms * (len(group) / row_count)
        records.extend(
            records_from_scores(
                group,
                scores=scores[positions].tolist(),
                model_id=model_id,
                latency_ms=group_latency,
            )
        )
    return records


def assert_parameters_unchanged(model: CrossEncoder, before: dict[str, torch.Tensor]) -> None:
    transformer = model.model
    if transformer is None:
        raise RuntimeError("cross-encoder has no underlying transformer model")
    after = transformer.state_dict()
    changed = [name for name, tensor in before.items() if not torch.equal(tensor, after[name])]
    if changed:
        raise AssertionError(f"unchanged baseline parameters were modified: {changed[:5]}")
