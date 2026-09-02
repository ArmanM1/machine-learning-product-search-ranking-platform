from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
performance_harness = importlib.import_module("scripts.performance_harness")


def test_percentile_uses_linear_interpolation() -> None:
    assert performance_harness._percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0
    assert performance_harness._percentile([10.0, 20.0, 30.0, 40.0], 0.95) == pytest.approx(38.5)


def test_development_harness_covers_declared_matrix_without_claiming_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = [{"query_id": f"q{count}", "candidate_count": count} for count in (10, 20, 40)]

    def fake_request(
        _base_url: str, path: str, _payload: dict[str, Any] | None = None
    ) -> tuple[Any, float]:
        if path == "/readyz":
            return {"status": "ready", "model_id": "candidate"}, 3.0
        if path.startswith("/api/v1/queries"):
            return queries, 2.0
        raise AssertionError(f"unexpected request path: {path}")

    def fake_rank(_base_url: str, query_id: str, _model_id: str, top_k: int) -> dict[str, Any]:
        assert query_id == f"q{top_k}"
        return {"ok": True, "end_to_end_ms": float(top_k), "model_ms": float(top_k) / 2}

    monkeypatch.setattr(performance_harness, "_json_request", fake_request)
    monkeypatch.setattr(performance_harness, "_rank_once", fake_rank)
    report = performance_harness.run_harness(
        "https://demo.example.test",
        model_id=None,
        measured_requests=3,
        warmup_requests=1,
    )
    assert len(report["conditions"]) == 9
    assert {
        (condition["candidate_count"], condition["concurrency"])
        for condition in report["conditions"]
    } == {(count, concurrency) for count in (10, 20, 40) for concurrency in (1, 4, 8)}
    assert all(condition["sample_count"] == 3 for condition in report["conditions"])
    assert report["production_claim_eligible"] is False


def test_harness_refuses_production_sized_request_count() -> None:
    with pytest.raises(ValueError, match="between 1 and 50"):
        performance_harness.run_harness(
            "https://demo.example.test",
            model_id="candidate",
            measured_requests=200,
            warmup_requests=0,
        )
