"""Checksum-verified ranker registry for immutable release images."""

from __future__ import annotations

import importlib
import logging
import math
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import numpy as np

from search_rank.artifacts.checksums import sha256_directory, sha256_file
from search_rank.logging import log_event
from search_rank.schemas.evidence import ReleaseManifest
from search_rank.schemas.model import ModelArtifact

from .query_store import CuratedQuery

if TYPE_CHECKING:
    import torch

_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)
LOGGER = logging.getLogger(__name__)


def _tokenize(value: str) -> list[str]:
    """Match the versioned BM25 tokenizer without importing training baselines."""

    return _TOKEN_PATTERN.findall(value.casefold())


def _rank_by_score(product_ids: Sequence[str], scores: Sequence[float]) -> list[int]:
    """Match canonical ranking semantics without importing the evaluation package."""

    if len(product_ids) != len(scores):
        raise ValueError("product_ids and scores must have equal length")
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("product_ids must be unique within a query")
    checked: list[float] = []
    for score in scores:
        numeric = float(score)
        if not math.isfinite(numeric):
            raise ValueError("scores must be finite")
        checked.append(numeric)
    return sorted(range(len(product_ids)), key=lambda index: (-checked[index], product_ids[index]))


@dataclass(frozen=True)
class RankedCandidate:
    product_id: str
    title: str
    score: float
    rank: int


@dataclass(frozen=True)
class RankingOutput:
    results: tuple[RankedCandidate, ...]
    latency_ms: float


class Ranker(Protocol):
    model_id: str
    artifact_checksum: str

    def rank(self, query: CuratedQuery) -> RankingOutput: ...


class _PairTokenizer(Protocol):
    def __call__(
        self,
        text: list[str],
        text_pair: list[str],
        *,
        padding: bool,
        truncation: str,
        return_tensors: str,
    ) -> Mapping[str, torch.Tensor]: ...


class _SequenceClassifierOutput(Protocol):
    logits: torch.Tensor


class _SequenceClassifier(Protocol):
    def __call__(self, **features: torch.Tensor) -> _SequenceClassifierOutput: ...


@dataclass(frozen=True)
class _SequenceClassifierRuntime:
    tokenizer: _PairTokenizer
    model: _SequenceClassifier


def _transformer_classes() -> tuple[Any, Any]:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    return AutoTokenizer, AutoModelForSequenceClassification


def _load_sequence_classifier(checkpoint: Path) -> _SequenceClassifierRuntime:
    """Load a standard local Hugging Face sequence-classification checkpoint."""

    log_event(LOGGER, "model_runtime_phase", phase="import_torch")
    importlib.import_module("torch")

    log_event(LOGGER, "model_runtime_phase", phase="import_transformers")
    auto_tokenizer, auto_model = _transformer_classes()

    checkpoint_path = str(checkpoint)
    log_event(LOGGER, "model_runtime_phase", phase="load_tokenizer")
    tokenizer = auto_tokenizer.from_pretrained(
        checkpoint_path,
        local_files_only=True,
        trust_remote_code=False,
    )
    log_event(LOGGER, "model_runtime_phase", phase="load_model")
    model = auto_model.from_pretrained(
        checkpoint_path,
        local_files_only=True,
        trust_remote_code=False,
    )
    model.to("cpu")
    model.eval()
    log_event(LOGGER, "model_runtime_phase", phase="model_ready")
    return _SequenceClassifierRuntime(
        tokenizer=cast(_PairTokenizer, tokenizer),
        model=cast(_SequenceClassifier, model),
    )


class LexicalRanker:
    def __init__(
        self,
        model_id: str = "bm25-v1",
        text_template: str = "enriched_v1",
        artifact_checksum: str = "sha256:" + "0" * 64,
    ) -> None:
        if text_template not in {"title_v1", "enriched_v1"}:
            raise ValueError(f"unsupported text template: {text_template}")
        self.model_id = model_id
        self.artifact_checksum = artifact_checksum
        self.text_template = text_template

    def rank(self, query: CuratedQuery) -> RankingOutput:
        from rank_bm25 import BM25Okapi

        started = time.perf_counter()
        corpus = [
            _tokenize(product.title if self.text_template == "title_v1" else product.text)
            for product in query.products
        ]
        model = BM25Okapi(corpus, k1=1.5, b=0.75)
        scores = np.asarray(model.get_scores(_tokenize(query.query)), dtype=float).tolist()
        order = _rank_by_score([product.product_id for product in query.products], scores)
        results = tuple(
            RankedCandidate(
                product_id=query.products[index].product_id,
                title=query.products[index].title,
                score=float(scores[index]),
                rank=rank,
            )
            for rank, index in enumerate(order, start=1)
        )
        return RankingOutput(results, (time.perf_counter() - started) * 1000)


class CrossEncoderRanker:
    def __init__(
        self,
        *,
        model_id: str,
        checkpoint: str | Path,
        artifact_checksum: str,
        batch_size: int = 32,
        text_template: str = "enriched_v1",
        runtime: _SequenceClassifierRuntime | None = None,
    ) -> None:
        if text_template not in {"title_v1", "enriched_v1"}:
            raise ValueError(f"unsupported text template: {text_template}")
        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        self.model_id = model_id
        self.artifact_checksum = artifact_checksum
        self.batch_size = batch_size
        self.text_template = text_template
        self._runtime = runtime or _load_sequence_classifier(Path(checkpoint))
        self.tokenizer = self._runtime.tokenizer
        self.model = self._runtime.model

    def _predict_raw_logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        import torch

        # CrossEncoder.predict sorts standard text pairs by descending character
        # length before batching, then restores caller order. Keep that batching
        # contract so this lean runtime produces the same raw checkpoint logits.
        sorted_indices = np.argsort([-sum(len(value) for value in pair) for pair in pairs])
        sorted_pairs = [pairs[int(index)] for index in sorted_indices]
        sorted_scores: list[float] = []
        with torch.inference_mode():
            for start in range(0, len(sorted_pairs), self.batch_size):
                batch = sorted_pairs[start : start + self.batch_size]
                features = self.tokenizer(
                    [query for query, _ in batch],
                    [text for _, text in batch],
                    padding=True,
                    truncation="longest_first",
                    return_tensors="pt",
                )
                cpu_features = {name: value.to("cpu") for name, value in features.items()}
                logits = self.model(**cpu_features).logits
                if logits.ndim == 2 and logits.shape[1] == 1:
                    logits = logits[:, 0]
                elif logits.ndim != 1:
                    raise ValueError("cross-encoder checkpoint must emit one logit per input pair")
                if logits.shape[0] != len(batch):
                    raise ValueError("cross-encoder prediction count differs from candidate rows")
                sorted_scores.extend(float(score) for score in logits.detach().cpu().tolist())
        restore_order = np.argsort(sorted_indices)
        return [sorted_scores[int(index)] for index in restore_order]

    def rank(self, query: CuratedQuery) -> RankingOutput:
        started = time.perf_counter()
        pairs = [
            (
                query.query,
                product.title if self.text_template == "title_v1" else product.text,
            )
            for product in query.products
        ]
        scores = self._predict_raw_logits(pairs)
        order = _rank_by_score([product.product_id for product in query.products], scores)
        results = tuple(
            RankedCandidate(
                product_id=query.products[index].product_id,
                title=query.products[index].title,
                score=scores[index],
                rank=rank,
            )
            for rank, index in enumerate(order, start=1)
        )
        return RankingOutput(results, (time.perf_counter() - started) * 1000)


def load_rankers(
    release_manifest_path: str | Path,
) -> tuple[dict[str, Ranker], dict[str, Any]]:
    manifest_path = Path(release_manifest_path)
    manifest = ReleaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    ).model_dump(
        mode="json",
        exclude_none=True,
    )
    if manifest["evidence_mode"] == "verified":
        artifact_path = manifest_path.parent / "candidate-model-artifact.json"
        artifact = ModelArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        artifact_file_checksum = "sha256:" + sha256_file(artifact_path)
        expected_file_checksum = manifest["artifact_checksums"].get("candidate-model-artifact.json")
        candidate = next(
            (
                model
                for model in manifest["models"]
                if model["model_id"] == artifact.model_id and model["kind"] == "fine_tuned"
            ),
            None,
        )
        if (
            artifact_file_checksum != expected_file_checksum
            or candidate is None
            or artifact.artifact_checksum != candidate["artifact_checksum"]
            or artifact.dataset_manifest_hash != manifest["dataset_manifest_hash"]
            or artifact.evaluation_report_id != manifest["evaluation_report_id"]
            or artifact.git_sha != manifest["provenance"]["training"]["git_sha"]
            or artifact.image_digest != manifest["provenance"]["training"]["image_digest"]
            or artifact.run_id != manifest["provenance"]["training"]["run_id"]
            or artifact.config_hash != manifest["provenance"]["training"]["config_hash"]
            or artifact.selected_training_run_manifest_sha256
            != manifest["provenance"]["training"]["run_manifest_sha256"]
            or artifact.evaluation_report_sha256
            != manifest["artifact_checksums"]["evaluation-report.json"]
            or artifact.promoted != (manifest["promoted_model_id"] == artifact.model_id)
        ):
            raise ValueError("candidate ModelArtifact differs from the verified release identity")
    rankers: dict[str, Ranker] = {}
    verified_checkpoints: dict[Path, tuple[str, _SequenceClassifierRuntime]] = {}
    for model in manifest["models"]:
        kind = model["kind"]
        ranker: Ranker
        if kind == "bm25":
            ranker = LexicalRanker(
                model["model_id"],
                text_template=str(model.get("text_template", "enriched_v1")),
                artifact_checksum=str(model["artifact_checksum"]),
            )
        elif kind in {"pretrained", "fine_tuned"}:
            checkpoint = (manifest_path.parent / model["checkpoint"]).resolve()
            verified = verified_checkpoints.get(checkpoint)
            if verified is None:
                actual = f"sha256:{sha256_directory(checkpoint)}"
            else:
                actual, runtime = verified
            if actual != model["artifact_checksum"]:
                raise ValueError(
                    f"model checksum mismatch for {model['model_id']}: expected "
                    f"{model['artifact_checksum']}, got {actual}"
                )
            if verified is None:
                runtime = _load_sequence_classifier(checkpoint)
                verified_checkpoints[checkpoint] = (actual, runtime)
            ranker = CrossEncoderRanker(
                model_id=model["model_id"],
                checkpoint=checkpoint,
                artifact_checksum=actual,
                batch_size=int(model.get("batch_size", 32)),
                text_template=str(model.get("text_template", "enriched_v1")),
                runtime=runtime,
            )
        else:
            raise ValueError(f"unsupported public model kind: {kind}")
        rankers[ranker.model_id] = ranker
    if manifest["promoted_model_id"] not in rankers:
        raise ValueError("promoted model is absent from release manifest")
    return rankers, manifest
