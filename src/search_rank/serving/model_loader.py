"""Checksum-verified ranker registry for immutable release images."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
from sentence_transformers import CrossEncoder

from search_rank.artifacts.checksums import sha256_directory
from search_rank.baselines.bm25 import tokenize
from search_rank.evaluation.metrics import rank_by_score

from .query_store import CuratedQuery


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


class _CrossEncoderPredictor(Protocol):
    def predict(
        self,
        sentences: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> Any: ...


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
            tokenize(product.title if self.text_template == "title_v1" else product.text)
            for product in query.products
        ]
        model = BM25Okapi(corpus, k1=1.5, b=0.75)
        scores = np.asarray(model.get_scores(tokenize(query.query)), dtype=float).tolist()
        order = rank_by_score([product.product_id for product in query.products], scores)
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
    ) -> None:
        if text_template not in {"title_v1", "enriched_v1"}:
            raise ValueError(f"unsupported text template: {text_template}")
        self.model_id = model_id
        self.artifact_checksum = artifact_checksum
        self.batch_size = batch_size
        self.text_template = text_template
        self.model = cast(
            CrossEncoder,
            CrossEncoder(str(checkpoint), device="cpu", trust_remote_code=False),
        )

    def rank(self, query: CuratedQuery) -> RankingOutput:
        started = time.perf_counter()
        pairs = [
            (
                query.query,
                product.title if self.text_template == "title_v1" else product.text,
            )
            for product in query.products
        ]
        scores = np.asarray(
            cast(_CrossEncoderPredictor, self.model).predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            ),
            dtype=float,
        ).reshape(-1)
        order = rank_by_score([product.product_id for product in query.products], scores.tolist())
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


def load_rankers(
    release_manifest_path: str | Path,
) -> tuple[dict[str, Ranker], dict[str, Any]]:
    manifest_path = Path(release_manifest_path)
    manifest = cast(
        dict[str, Any],
        json.loads(manifest_path.read_text(encoding="utf-8")),
    )
    rankers: dict[str, Ranker] = {}
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
            actual = f"sha256:{sha256_directory(checkpoint)}"
            if actual != model["artifact_checksum"]:
                raise ValueError(
                    f"model checksum mismatch for {model['model_id']}: expected "
                    f"{model['artifact_checksum']}, got {actual}"
                )
            ranker = CrossEncoderRanker(
                model_id=model["model_id"],
                checkpoint=checkpoint,
                artifact_checksum=actual,
                batch_size=int(model.get("batch_size", 32)),
                text_template=str(model.get("text_template", "enriched_v1")),
            )
        else:
            raise ValueError(f"unsupported public model kind: {kind}")
        rankers[ranker.model_id] = ranker
    if manifest["promoted_model_id"] not in rankers:
        raise ValueError("promoted model is absent from release manifest")
    return rankers, manifest
