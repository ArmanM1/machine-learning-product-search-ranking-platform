from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
import torch

import search_rank.training.trainer as trainer
from search_rank.schemas.experiment import ExperimentConfig


class _TinyBatch(dict[str, torch.Tensor]):
    def to(self, device: str) -> _TinyBatch:
        return _TinyBatch({name: value.to(device) for name, value in self.items()})


class _TinyTokenizer:
    def __call__(
        self,
        queries: list[str],
        texts: list[str],
        **_: Any,
    ) -> _TinyBatch:
        del queries
        features = [[1.0 if "positive" in text else -1.0] for text in texts]
        return _TinyBatch(features=torch.tensor(features, dtype=torch.float32))


class _TinyTransformer(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.linear = torch.nn.Linear(1, 1)
        with torch.no_grad():
            self.linear.weight.fill_(-1.0)
            self.linear.bias.zero_()

    def forward(self, features: torch.Tensor) -> SimpleNamespace:
        return SimpleNamespace(logits=self.linear(features))


class _TinyCrossEncoder:
    def __init__(self, source: str | Path | None = None, **_: Any) -> None:
        self.model = _TinyTransformer()
        self.tokenizer = _TinyTokenizer()
        if source is not None and (Path(source) / "weights.pt").is_file():
            state = torch.load(Path(source) / "weights.pt", map_location="cpu", weights_only=True)
            self.model.load_state_dict(state)

    def predict(self, sentences: list[tuple[str, str]], **_: Any) -> np.ndarray[Any, Any]:
        batch = self.tokenizer(
            [query for query, _ in sentences],
            [text for _, text in sentences],
        )
        self.model.eval()
        with torch.no_grad():
            return self.model(**batch).logits.reshape(-1).numpy()

    def save_pretrained(self, path: str, **_: Any) -> None:
        destination = Path(path)
        destination.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), destination / "weights.pt")


def _config() -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "config_id": "tiny-overfit",
            "config_hash": f"sha256:{'a' * 64}",
            "seed": 42,
            "dataset_manifest_hash": f"sha256:{'b' * 64}",
            "input_template_version": "enriched_v1",
            "base_model_id": "tiny-local-model",
            "base_model_revision": "fixture-v1",
            "base_model_license": "MIT",
            "max_sequence_length": 8,
            "loss_name": "BinaryCrossEntropyLoss",
            "label_mapping_version": "project_graded_v1",
            "sampling_strategy": "random_only_v1",
            "hard_example_sources": [],
            "learning_rate": 0.5,
            "effective_batch_size": 4,
            "gradient_accumulation_steps": 1,
            "max_epochs": 6,
            "warmup_ratio": 1 / 6,
            "early_stopping": False,
            "precision": "float32",
            "deterministic_mode": True,
            "requested_hardware": "local-test-cpu",
        }
    )


def _training_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "query": "fixture",
                "input_text": text,
                "target": target,
                "query_id": f"train-{index}",
                "project_split": "train",
            }
            for index, (text, target) in enumerate(
                [
                    ("positive item", 1.0),
                    ("negative item", 0.0),
                    ("positive duplicate", 1.0),
                    ("negative duplicate", 0.0),
                ]
            )
        ]
    )


def _validation_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "query": "fixture",
                "query_id": "validation-query",
                "product_id": "positive",
                "esci_label": "Exact",
                "project_split": "validation",
                "text_enriched_v1": "positive item",
            },
            {
                "query": "fixture",
                "query_id": "validation-query",
                "product_id": "negative",
                "esci_label": "Irrelevant",
                "project_split": "validation",
                "text_enriched_v1": "negative item",
            },
        ]
    )


@pytest.mark.slow
def test_tiny_torch_model_overfits_and_selected_checkpoint_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trainer, "_model", lambda config, device: _TinyCrossEncoder())
    monkeypatch.setattr(trainer, "CrossEncoder", _TinyCrossEncoder)
    monkeypatch.setattr(
        trainer,
        "load_checkpoint",
        lambda path, device="cpu": _TinyCrossEncoder(path),
    )
    validation = _validation_rows()
    initial_metric = trainer._validation_metric(
        _TinyCrossEncoder(), validation, text_column="text_enriched_v1", batch_size=2
    )

    result = trainer.train_candidate(
        _training_rows(),
        validation,
        _config(),
        output_dir=tmp_path / "run",
        device="cpu",
    )

    assert result.best_validation_ndcg_at_10 > initial_metric
    assert result.best_validation_ndcg_at_10 == pytest.approx(1.0)
    assert result.changed_parameter_count > 0
    assert result.fresh_load_verified is True
    assert Path(result.best_checkpoint, "weights.pt").is_file()
    assert result.warmup_steps == 1
