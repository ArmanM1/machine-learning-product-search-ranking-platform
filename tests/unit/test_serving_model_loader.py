from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import torch

from search_rank.serving import model_loader
from search_rank.serving.query_store import CuratedProduct, CuratedQuery


class _RecordingTokenizer:
    def __init__(self, token_by_text: dict[str, int]) -> None:
        self.token_by_text = token_by_text
        self.calls: list[tuple[list[str], list[str], dict[str, Any]]] = []

    def __call__(
        self,
        text: list[str],
        text_pair: list[str],
        **options: Any,
    ) -> dict[str, torch.Tensor]:
        self.calls.append((list(text), list(text_pair), options))
        return {
            "input_ids": torch.tensor(
                [[self.token_by_text[candidate]] for candidate in text_pair],
                dtype=torch.long,
            )
        }


class _RawLogitClassifier:
    def __init__(self, score_by_token: dict[int, float]) -> None:
        self.score_by_token = score_by_token
        self.batch_sizes: list[int] = []

    def __call__(self, **features: torch.Tensor) -> SimpleNamespace:
        tokens = features["input_ids"][:, 0].tolist()
        self.batch_sizes.append(len(tokens))
        return SimpleNamespace(
            logits=torch.tensor(
                [[self.score_by_token[int(token)]] for token in tokens],
                dtype=torch.float32,
            )
        )


def test_direct_classifier_preserves_raw_logits_batching_and_ranking(tmp_path: Path) -> None:
    texts = {
        "p3": "x",
        "p2": "medium text",
        "p4": "the considerably longest candidate document",
        "p1": "short",
    }
    token_by_text = {text: index for index, text in enumerate(texts.values(), start=1)}
    score_by_token = {
        token_by_text[texts["p3"]]: 0.25,
        token_by_text[texts["p2"]]: 2.5,
        token_by_text[texts["p4"]]: 2.5,
        token_by_text[texts["p1"]]: -1.25,
    }
    tokenizer = _RecordingTokenizer(token_by_text)
    classifier = _RawLogitClassifier(score_by_token)
    runtime = model_loader._SequenceClassifierRuntime(
        tokenizer=tokenizer,  # type: ignore[arg-type]
        model=classifier,  # type: ignore[arg-type]
    )
    ranker = model_loader.CrossEncoderRanker(
        model_id="fixture-model",
        checkpoint=tmp_path / "unused-checkpoint",
        artifact_checksum="sha256:" + "a" * 64,
        batch_size=2,
        text_template="enriched_v1",
        runtime=runtime,
    )
    query = CuratedQuery(
        query_id="q1",
        query="product search",
        products=tuple(
            CuratedProduct(product_id, f"Title {product_id}", texts[product_id])
            for product_id in ("p3", "p2", "p4", "p1")
        ),
    )

    output = ranker.rank(query)

    assert classifier.batch_sizes == [2, 2]
    assert [candidate for call in tokenizer.calls for candidate in call[1]] == [
        texts["p4"],
        texts["p2"],
        texts["p1"],
        texts["p3"],
    ]
    assert all(
        options
        == {
            "padding": True,
            "truncation": "longest_first",
            "return_tensors": "pt",
        }
        for _, _, options in tokenizer.calls
    )
    assert [result.product_id for result in output.results] == ["p2", "p4", "p3", "p1"]
    assert [result.score for result in output.results] == pytest.approx([2.5, 2.5, 0.25, -1.25])
    assert [result.rank for result in output.results] == [1, 2, 3, 4]


def test_checkpoint_loading_is_local_only_and_places_model_on_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    tokenizer = object()

    class _LoadedModel:
        def __init__(self) -> None:
            self.devices: list[str] = []
            self.eval_calls = 0

        def to(self, device: str) -> _LoadedModel:
            self.devices.append(device)
            return self

        def eval(self) -> _LoadedModel:
            self.eval_calls += 1
            return self

    loaded_model = _LoadedModel()
    calls: list[tuple[str, str, dict[str, object]]] = []

    def load_tokenizer(path: str, **options: object) -> object:
        calls.append(("tokenizer", path, options))
        return tokenizer

    def load_model(path: str, **options: object) -> _LoadedModel:
        calls.append(("model", path, options))
        return loaded_model

    monkeypatch.setattr(
        model_loader.AutoTokenizer,
        "from_pretrained",
        staticmethod(load_tokenizer),
    )
    monkeypatch.setattr(
        model_loader.AutoModelForSequenceClassification,
        "from_pretrained",
        staticmethod(load_model),
    )

    runtime = model_loader._load_sequence_classifier(checkpoint)

    assert runtime.tokenizer is tokenizer
    assert runtime.model is loaded_model
    assert calls == [
        (
            "tokenizer",
            str(checkpoint),
            {"local_files_only": True, "trust_remote_code": False},
        ),
        (
            "model",
            str(checkpoint),
            {"local_files_only": True, "trust_remote_code": False},
        ),
    ]
    assert loaded_model.devices == ["cpu"]
    assert loaded_model.eval_calls == 1


def _summary(model_id: str, checksum: str, *, promoted: bool) -> dict[str, object]:
    return {
        "model_id": model_id,
        "display_name": model_id,
        "kind": "pretrained",
        "base_model_id": "fixture/base-model",
        "artifact_checksum": checksum,
        "evaluation_report_id": "report-fixture",
        "promoted_at": "2026-09-18T00:00:00Z" if promoted else None,
        "limitations_url": "/methodology#limitations",
    }


def test_duplicate_manifest_checkpoints_share_checksum_tokenizer_and_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "models" / "pretrained"
    checkpoint.mkdir(parents=True)
    checksum = "sha256:" + "a" * 64
    manifest = {
        "schema_version": "1.0.0",
        "release_id": "release-fixture",
        "promoted_model_id": "neural-enriched",
        "dataset_manifest_hash": "sha256:" + "b" * 64,
        "split_manifest_hash": "sha256:" + "c" * 64,
        "evaluation_report_id": "report-fixture",
        "git_sha": "abcdef0",
        "evidence_mode": "validation_only",
        "artifact_checksums": {
            name: "sha256:" + "d" * 64
            for name in (
                "baseline-summary.json",
                "curated-queries.json",
                "public-evidence.json",
                "LICENSE",
                "NOTICE",
            )
        },
        "models": [
            {
                "model_id": "neural-enriched",
                "kind": "pretrained",
                "checkpoint": "models/pretrained",
                "text_template": "enriched_v1",
                "artifact_checksum": checksum,
                "batch_size": 32,
                "public_summary": _summary("neural-enriched", checksum, promoted=True),
            },
            {
                "model_id": "neural-title",
                "kind": "pretrained",
                "checkpoint": "models/pretrained",
                "text_template": "title_v1",
                "artifact_checksum": checksum,
                "batch_size": 16,
                "public_summary": _summary("neural-title", checksum, promoted=False),
            },
        ],
    }
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tokenizer = object()
    classifier = object()
    runtime = model_loader._SequenceClassifierRuntime(
        tokenizer=tokenizer,  # type: ignore[arg-type]
        model=classifier,  # type: ignore[arg-type]
    )
    checksum_calls: list[Path] = []
    load_calls: list[Path] = []

    def calculate_checksum(path: Path) -> str:
        checksum_calls.append(path)
        return "a" * 64

    def load_runtime(path: Path) -> model_loader._SequenceClassifierRuntime:
        load_calls.append(path)
        return runtime

    monkeypatch.setattr(model_loader, "sha256_directory", calculate_checksum)
    monkeypatch.setattr(model_loader, "_load_sequence_classifier", load_runtime)

    rankers, _ = model_loader.load_rankers(manifest_path)

    assert checksum_calls == [checkpoint.resolve()]
    assert load_calls == [checkpoint.resolve()]
    enriched = rankers["neural-enriched"]
    title = rankers["neural-title"]
    assert isinstance(enriched, model_loader.CrossEncoderRanker)
    assert isinstance(title, model_loader.CrossEncoderRanker)
    assert enriched.tokenizer is title.tokenizer is tokenizer
    assert enriched.model is title.model is classifier
    assert enriched.batch_size == 32
    assert title.batch_size == 16


def test_serving_helpers_match_canonical_tokenization_and_ranking() -> None:
    from search_rank.baselines.bm25 import tokenize
    from search_rank.evaluation.metrics import rank_by_score

    for value in ("Caf\u00e9 MUG-Set 42", "Stra\u00dfe_and_symbols!", "\u6771\u4eac  travel"):
        assert model_loader._tokenize(value) == tokenize(value)

    product_ids = ["p3", "p1", "p2"]
    scores = [0.5, 1.0, 1.0]
    assert model_loader._rank_by_score(product_ids, scores) == rank_by_score(
        product_ids, scores
    )


def test_importing_serving_loader_does_not_import_sentence_transformers() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import search_rank.serving.model_loader; "
            "assert not any(name.startswith('sentence_transformers') for name in sys.modules)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
