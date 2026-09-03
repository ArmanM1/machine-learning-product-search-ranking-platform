from __future__ import annotations

import json
import random
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
        self.dropout = torch.nn.Dropout(p=0.25)
        self.linear = torch.nn.Linear(1, 1)
        with torch.no_grad():
            self.linear.weight.fill_(-1.0)
            self.linear.bias.zero_()

    def forward(self, features: torch.Tensor) -> SimpleNamespace:
        return SimpleNamespace(logits=self.linear(self.dropout(features)))


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

    uninterrupted = trainer.train_candidate(
        _training_rows(),
        validation,
        _config(),
        output_dir=tmp_path / "uninterrupted-run",
        device="cpu",
    )

    actual_validation = trainer._validation_metric
    validation_calls = 0

    def interrupt_during_second_epoch(*args: Any, **kwargs: Any) -> float:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise RuntimeError("simulated spot interruption")
        return actual_validation(*args, **kwargs)

    monkeypatch.setattr(trainer, "_validation_metric", interrupt_during_second_epoch)
    with pytest.raises(RuntimeError, match="simulated spot interruption"):
        trainer.train_candidate(
            _training_rows(),
            validation,
            _config(),
            output_dir=tmp_path / "interrupted-run",
            device="cpu",
            checkpoint_dir=tmp_path / "managed-spot-checkpoints",
        )
    assert [path.name for path in (tmp_path / "managed-spot-checkpoints").glob("epoch-*")] == [
        "epoch-0001"
    ]

    monkeypatch.setattr(trainer, "_validation_metric", actual_validation)
    result = trainer.train_candidate(
        _training_rows(),
        validation,
        _config(),
        output_dir=tmp_path / "run",
        device="cpu",
        checkpoint_dir=tmp_path / "managed-spot-checkpoints",
    )

    assert result.best_validation_ndcg_at_10 > initial_metric
    assert result.best_validation_ndcg_at_10 == pytest.approx(1.0)
    assert result.changed_parameter_count > 0
    assert result.fresh_load_verified is True
    assert Path(result.best_checkpoint, "weights.pt").is_file()
    assert result.warmup_steps == 1
    uninterrupted_weights = torch.load(
        Path(uninterrupted.best_checkpoint) / "weights.pt",
        map_location="cpu",
        weights_only=True,
    )
    resumed_weights = torch.load(
        Path(result.best_checkpoint) / "weights.pt", map_location="cpu", weights_only=True
    )
    assert uninterrupted_weights.keys() == resumed_weights.keys()
    assert all(
        torch.equal(uninterrupted_weights[name], resumed_weights[name])
        for name in uninterrupted_weights
    )
    assert result.best_validation_ndcg_at_10 == uninterrupted.best_validation_ndcg_at_10
    uninterrupted_curves = json.loads(Path(uninterrupted.curves_path).read_text(encoding="utf-8"))
    resumed_curves = json.loads(Path(result.curves_path).read_text(encoding="utf-8"))
    assert resumed_curves == uninterrupted_curves
    completed = sorted((tmp_path / "managed-spot-checkpoints").glob("epoch-*"))
    assert len(completed) == result.epochs_completed
    assert all(
        (path / "COMPLETE").read_text(encoding="utf-8").startswith("sha256:") for path in completed
    )
    assert all((path / "optimizer-state.pt").is_file() for path in completed)
    assert all((path / "checkpoint-manifest.json").is_file() for path in completed)

    def unexpected_validation(*_: Any, **__: Any) -> float:
        raise AssertionError("a completed managed-spot checkpoint must not retrain")

    monkeypatch.setattr(trainer, "_validation_metric", unexpected_validation)
    resumed = trainer.train_candidate(
        _training_rows(),
        validation,
        _config(),
        output_dir=tmp_path / "resumed-run",
        device="cpu",
        checkpoint_dir=tmp_path / "managed-spot-checkpoints",
    )
    assert resumed.epochs_completed == result.epochs_completed
    assert resumed.optimizer_steps == result.optimizer_steps
    assert resumed.best_validation_ndcg_at_10 == result.best_validation_ndcg_at_10
    assert Path(resumed.best_checkpoint, "weights.pt").is_file()

    (completed[-1] / "optimizer-state.pt").write_bytes(b"corrupt-after-sync")
    incomplete = tmp_path / "managed-spot-checkpoints" / "epoch-9999"
    incomplete.mkdir()
    (incomplete / "COMPLETE").write_text("sha256:" + "0" * 64 + "\n", encoding="utf-8")
    fallback = trainer._load_resume_checkpoint(tmp_path / "managed-spot-checkpoints", _config())
    assert fallback is not None
    assert fallback.completed_epoch == result.epochs_completed - 1


def test_python_numpy_and_torch_rng_state_round_trip() -> None:
    trainer.configure_determinism(77, strict=True)
    state = trainer._capture_rng_state()
    expected = (random.random(), float(np.random.random()), torch.rand(3))
    random.random()
    np.random.random()
    torch.rand(3)

    trainer._restore_rng_state(state)
    actual = (random.random(), float(np.random.random()), torch.rand(3))

    assert actual[0] == expected[0]
    assert actual[1] == expected[1]
    assert torch.equal(actual[2], expected[2])


def test_cuda_rng_state_is_captured_and_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    cuda_states = [
        torch.tensor([1, 2, 3], dtype=torch.uint8),
        torch.tensor([4, 5, 6], dtype=torch.uint8),
    ]
    restored: list[torch.Tensor] = []
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: len(cuda_states))
    monkeypatch.setattr(
        torch.cuda, "get_rng_state_all", lambda: [item.clone() for item in cuda_states]
    )
    monkeypatch.setattr(
        torch.cuda,
        "set_rng_state_all",
        lambda states: restored.extend(item.clone() for item in states),
    )

    state = trainer._capture_rng_state()
    trainer._restore_rng_state(state)

    assert len(restored) == len(cuda_states)
    assert all(
        torch.equal(actual, expected)
        for actual, expected in zip(restored, cuda_states, strict=True)
    )


def test_cuda_request_fails_closed_when_cuda_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    with pytest.raises(RuntimeError, match="requested but CUDA is unavailable"):
        trainer._resolve_training_device("cuda")
