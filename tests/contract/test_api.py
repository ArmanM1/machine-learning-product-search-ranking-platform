from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from search_rank.serving.app import create_app
from search_rank.serving.dependencies import ServiceSettings, ServiceState
from search_rank.serving.model_loader import RankedCandidate, RankingOutput
from search_rank.serving.query_store import CuratedProduct, CuratedQuery, QueryStore


@dataclass
class FakeRanker:
    model_id: str
    reverse: bool = False
    artifact_checksum: str = "sha256:" + "1" * 64

    def rank(self, query: CuratedQuery) -> RankingOutput:
        products = list(query.products)
        if self.reverse:
            products.reverse()
        return RankingOutput(
            tuple(
                RankedCandidate(product.product_id, product.title, 1.0 / rank, rank)
                for rank, product in enumerate(products, start=1)
            ),
            1.25,
        )


def client() -> TestClient:
    query = CuratedQuery(
        "q1",
        "travel mug",
        (
            CuratedProduct("p1", "Insulated mug", "Title: Insulated mug", "Exact"),
            CuratedProduct("p2", "Mug rack", "Title: Mug rack", "Complement"),
        ),
    )
    promoted = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    manifest = {
        "promoted_model_id": "candidate-v1",
        "dataset_manifest_hash": "sha256:" + "2" * 64,
        "models": [
            {
                "public_summary": {
                    "model_id": model_id,
                    "display_name": model_id,
                    "kind": kind,
                    "base_model_id": None if kind == "bm25" else "base",
                    "artifact_checksum": "sha256:" + "1" * 64,
                    "evaluation_report_id": "report-v1",
                    "promoted_at": promoted,
                    "limitations_url": "/limitations",
                }
            }
            for model_id, kind in [("bm25-v1", "bm25"), ("candidate-v1", "fine_tuned")]
        ],
    }
    settings = ServiceSettings(service_version="test")
    state = ServiceState(
        settings,
        query_store=QueryStore([query]),
        rankers={
            "bm25-v1": FakeRanker("bm25-v1"),
            "candidate-v1": FakeRanker("candidate-v1", reverse=True),
        },
        release_manifest=manifest,
    )
    return TestClient(create_app(settings, state=state))


def test_health_and_readiness() -> None:
    with client() as api:
        assert api.get("/healthz").json() == {"status": "ok", "service_version": "test"}
        ready = api.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["model_id"] == "candidate-v1"


def test_rank_is_bounded_to_curated_query() -> None:
    with client() as api:
        response = api.post(
            "/api/v1/rank", json={"query_id": "q1", "model_id": "candidate-v1", "top_k": 2}
        )
        assert response.status_code == 200
        assert [item["product_id"] for item in response.json()["results"]] == ["p2", "p1"]
        assert (
            api.post(
                "/api/v1/rank", json={"query_id": "unknown", "model_id": "candidate-v1", "top_k": 2}
            ).status_code
            == 404
        )
        assert (
            api.post(
                "/api/v1/rank", json={"query_id": "q1", "model_id": "candidate-v1", "top_k": 41}
            ).status_code
            == 422
        )


def test_comparison_distinguishes_judgments() -> None:
    with client() as api:
        response = api.get(
            "/api/v1/comparisons/q1",
            params={
                "baseline": "bm25-v1",
                "candidate": "candidate-v1",
                "include_judgments": "true",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["rank_movements"][0]["rank_delta"] == -1
        assert payload["benchmark_judgments"][0]["source"] == "ground_truth_annotation"


def test_openapi_and_errors_are_sanitized() -> None:
    with client() as api:
        assert api.get("/openapi.json").status_code == 200
        error = api.get("/api/v1/runs/private").json()
        assert error["code"] == "unknown_run"
        assert "stack" not in error
