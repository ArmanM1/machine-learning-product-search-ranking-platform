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
    pairs = [
        (str(row.query), str(getattr(row, text_column))) for row in frame.itertuples(index=False)
    ]
    started = time.perf_counter()
    predicted = cast(_CrossEncoderPredictor, model).predict(
        pairs,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    elapsed = (time.perf_counter() - started) * 1000
    scored = frame.copy()
    scored["_model_score"] = np.asarray(predicted, dtype=float).reshape(-1)
    records: list[ScoredProduct] = []
    for _, group in scored.groupby("query_id", sort=True):
        group_latency = elapsed * (len(group) / max(len(scored), 1))
        records.extend(
            records_from_scores(
                group.drop(columns=["_model_score"]),
                scores=group["_model_score"].astype(float).tolist(),
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
