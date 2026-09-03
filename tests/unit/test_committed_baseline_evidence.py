"""Integrity checks for the sanitized local baseline reproducibility evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "evidence" / "baselines" / "milestone-2-validation.json"
STATUS_PATH = ROOT / "evidence" / "status.json"
DATA_EVIDENCE_PATH = ROOT / "evidence" / "data" / "milestone-1-reproducibility.json"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
ABSOLUTE_LOCAL_PATH = re.compile(r"(?i)(?:^[a-z]:[\\/]|[\\/]users[\\/]|/home/)")
SYSTEM_IDS = {
    "bm25-v1-text_enriched_v1-unicode_words_casefold_v1-k1-1.5-b-0.75",
    "bm25-v1-text_title_v1-unicode_words_casefold_v1-k1-1.5-b-0.75",
    "input-order-v1",
    "pretrained-cross-encoder@233902d25c440f23af6f7d6e94d2946bac0bee0a-enriched_v1",
    "pretrained-cross-encoder@233902d25c440f23af6f7d6e94d2946bac0bee0a-title_v1",
    "seeded-random-v1-seed-42",
}
METRIC_NAMES = {
    "exact_mrr@10",
    "exact_top_1_rate",
    "graded_ndcg@10",
    "graded_ndcg@5",
    "pairwise_ordinal_accuracy",
    "recall_exact_or_substitute@10",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


def test_baseline_evidence_is_sanitized_and_scoped() -> None:
    evidence = _load(EVIDENCE_PATH)
    assert evidence["status"] == "quality_and_ranking_reproducibility_complete"
    assert evidence["independent_scoring_processes"] == 2
    assert evidence["runs"]["original_scoring"]["repository_dirty"] is True
    assert evidence["runs"]["independent_reproduction"]["repository_dirty"] is True
    assert evidence["verification"] == {
        "quality_metrics_exact_match": True,
        "rank_order_exact_match": True,
        "scores_exact_match": True,
        "all_non_latency_ranking_fields_exact_match": True,
        "quality_and_ranking_reproducibility_complete": True,
        "latency_reproducibility_complete": False,
        "clean_checkout_reproducibility_complete": False,
        "quality_metric_matrix_sha256": (
            "sha256:97c95049c748607a9a95f310bd72148f8c7174bd0ffadfd56f577ff5bcb4614c"
        ),
    }
    assert all(not ABSOLUTE_LOCAL_PATH.search(value) for value in _strings(evidence))
    assert "amokh" not in EVIDENCE_PATH.read_text(encoding="utf-8").casefold()


def test_all_six_systems_bind_quality_rank_score_and_separate_transport() -> None:
    evidence = _load(EVIDENCE_PATH)
    systems = evidence["systems"]
    assert set(systems) == SYSTEM_IDS

    metrics = {}
    for system_id, system in systems.items():
        metrics[system_id] = system["quality_metrics"]
        assert set(system["quality_metrics"]) == METRIC_NAMES
        assert system["quality_metrics_exact_match"] is True
        assert system["metric_query_count_per_metric"] == 2057
        assert system["metric_excluded_query_count_per_metric"] == 0

        ranking = system["ranking"]
        assert ranking["row_count"] == 41500
        assert ranking["semantic_match"] is True
        assert ranking["only_differing_field"] == "latency_ms"
        assert 0 < ranking["differing_latency_value_count"] <= ranking["row_count"]
        assert SHA256.fullmatch(ranking["rank_order_sha256"])
        assert SHA256.fullmatch(ranking["rank_and_score_sha256"])
        transport = ranking["raw_transport_sha256"]
        assert transport["equal"] is False
        assert SHA256.fullmatch(transport["original"])
        assert SHA256.fullmatch(transport["reproduction"])
        assert transport["original"] != transport["reproduction"]

        latency = system["p95_offline_inference_ms"]
        assert latency["original"] > 0
        assert latency["reproduction"] > 0
        assert math.isclose(
            latency["reproduction"] - latency["original"],
            latency["reproduction_minus_original_ms"],
            rel_tol=0,
            abs_tol=1e-12,
        )
        assert math.isclose(
            (latency["reproduction"] / latency["original"] - 1) * 100,
            latency["relative_change_percent"],
            rel_tol=0,
            abs_tol=1e-12,
        )

    assert _canonical_sha256(metrics) == evidence["verification"]["quality_metric_matrix_sha256"]


def test_query_identity_and_public_claim_boundary_are_consistent() -> None:
    evidence = _load(EVIDENCE_PATH)
    data_evidence = _load(DATA_EVIDENCE_PATH)
    status = _load(STATUS_PATH)

    assert (
        evidence["query_set"]["sorted_query_id_sha256"]
        == data_evidence["split_query_id_hashes"]["validation"]
    )
    assert evidence["dataset"]["manifest_sha256"] == data_evidence["processed_checksum"]
    claim = status["claim_boundary"]
    assert claim["validation_baseline_two_scoring_processes_completed"] is True
    assert claim["validation_baseline_quality_reproducibility_verified"] is True
    assert claim["validation_baseline_ranking_and_score_reproducibility_verified"] is True
    assert claim["validation_baseline_latency_reproducibility_verified"] is False
    assert claim["validation_baseline_clean_checkout_reproducibility_verified"] is False
    assert claim["baselines_verified"] is False
