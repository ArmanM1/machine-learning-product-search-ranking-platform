from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from search_rank.schemas.api import (
    ComparisonResponse,
    PublicEvidenceEnvelope,
    RankMovement,
    RankRequest,
    RankResponse,
)

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def test_rank_request_applies_default_and_bounds() -> None:
    assert RankRequest(query_id="q", model_id="m").top_k == 10
    with pytest.raises(ValidationError, match="less_than_equal"):
        RankRequest(query_id="q", model_id="m", top_k=41)


def test_rank_response_enforces_provenance_counts_and_contiguous_ranks() -> None:
    values: dict[str, Any] = {
        "request_id": "request-1",
        "query_id": "q",
        "query": "red shoes",
        "model_id": "candidate",
        "model_artifact_checksum": SHA_A,
        "dataset_manifest_hash": SHA_B,
        "candidate_count": 2,
        "top_k": 2,
        "latency_ms": 2.5,
        "results": [
            {"rank": 1, "product_id": "p1", "title": "One", "score": 0.9},
            {"rank": 2, "product_id": "p2", "title": "Two", "score": 0.8},
        ],
    }
    assert RankResponse.model_validate(values).results[0].product_id == "p1"
    values["results"][1]["rank"] = 3
    with pytest.raises(ValidationError, match="contiguous"):
        RankResponse.model_validate(values)


def test_rank_movement_sign_is_unambiguous() -> None:
    assert (
        RankMovement(product_id="p", baseline_rank=8, candidate_rank=3, rank_delta=5).rank_delta
        == 5
    )
    with pytest.raises(ValidationError, match="baseline_rank - candidate_rank"):
        RankMovement(product_id="p", baseline_rank=8, candidate_rank=3, rank_delta=-5)


def test_comparison_rejects_different_candidate_lists() -> None:
    values = {
        "request_id": "request-1",
        "query_id": "q",
        "query": "red shoes",
        "baseline_model_id": "bm25",
        "candidate_model_id": "candidate",
        "candidate_count": 1,
        "baseline_latency_ms": 1,
        "candidate_latency_ms": 2,
        "baseline_results": [{"rank": 1, "product_id": "p1", "title": "One", "score": 0.9}],
        "candidate_results": [{"rank": 1, "product_id": "p2", "title": "Two", "score": 0.8}],
        "rank_movements": [
            {"product_id": "p1", "baseline_rank": 1, "candidate_rank": 1, "rank_delta": 0}
        ],
    }
    with pytest.raises(ValidationError, match="identical products"):
        ComparisonResponse.model_validate(values)


def public_evidence_values() -> dict[str, Any]:
    interval = {
        "point_estimate": 0.05,
        "lower": 0.01,
        "upper": 0.09,
        "confidence_level": 0.95,
    }
    return {
        "schema_version": "1.0.0",
        "evidence_mode": "verified",
        "run": {
            "evidence_mode": "verified",
            "run_id": "run-1",
            "status": "complete",
            "config_hash": SHA_A,
            "dataset_manifest_hash": SHA_B,
            "git_sha": "abcdef1",
            "image_digest": SHA_A,
            "model_artifact_checksum": SHA_B,
            "dataset_name": "Amazon Shopping Queries ESCI",
            "dataset_version": "small-v1",
            "locale": "us",
            "base_model_id": "cross-encoder/model",
            "base_model_revision": "233e41b",
            "training_strategy": "mixed difficult and seeded-random examples",
            "hardware_class": "ml.g4dn.xlarge",
            "region": "us-east-1",
            "metrics": {
                "candidate_graded_ndcg_at_10": 0.70,
                "strongest_baseline_graded_ndcg_at_10": 0.65,
                "candidate_minus_baseline_graded_ndcg_at_10": 0.05,
            },
            "intervals": {"candidate_minus_baseline_graded_ndcg_at_10": interval},
            "duration_seconds": 120.0,
            "actual_cost_usd": None,
            "cost_evidence": "Billing reconciliation is pending.",
            "test_access_count": 1,
            "limitations": ["Reranks only a supplied candidate set."],
            "prohibited_claims": ["No claim of shopper impact."],
            "reproduction_command": "search-rank reproduce --run-id run-1",
        },
        "evaluation": {
            "evidence_mode": "verified",
            "report_id": "report-1",
            "run_id": "run-1",
            "candidate_model_id": "candidate-v1",
            "strongest_baseline_model_id": "bm25-v1",
            "release_status": "passed",
            "primary_metric": {
                "metric": "graded_ndcg@10",
                "display_name": "Graded nDCG@10",
                "value": 0.70,
            },
            "strongest_baseline": {
                "metric": "graded_ndcg@10",
                "display_name": "BM25",
                "value": 0.65,
            },
            "delta": {
                "metric": "graded_ndcg@10",
                "display_name": "Candidate minus strongest baseline",
                "value": 0.05,
                "interval": interval,
            },
            "held_out_query_count": 100,
            "bootstrap_resamples": 10_000,
            "bootstrap_seed": 42,
            "test_access_count": 1,
            "excluded_query_count": 2,
            "exclusion_note": "Two zero-gain queries were excluded from graded nDCG.",
            "models": [
                {
                    "model_id": "bm25-v1",
                    "display_name": "BM25",
                    "kind": "bm25",
                    "graded_ndcg_at_10": 0.65,
                },
                {
                    "model_id": "candidate-v1",
                    "display_name": "Fine-tuned candidate",
                    "kind": "fine_tuned",
                    "graded_ndcg_at_10": 0.70,
                    "exact_mrr_at_10": 0.72,
                    "p95_inference_latency_ms": 80.0,
                },
            ],
            "secondary_metrics": [],
        },
        "failure_analysis": {
            "evidence_mode": "verified",
            "run_id": "run-1",
            "metric": "graded_ndcg@10",
            "minimum_slice_size": 30,
            "slices": [
                {
                    "slice_id": "query_token_length:2_tokens",
                    "display_name": "Two-token queries",
                    "description": "Predeclared query-token-length slice.",
                    "query_count": 40,
                    "excluded_query_count": 0,
                    "baseline_graded_ndcg_at_10": 0.60,
                    "candidate_graded_ndcg_at_10": 0.62,
                    "delta": 0.02,
                    "low_sample": False,
                    "finding": "uncertain",
                }
            ],
            "examples": [
                {
                    "example_id": "query-1",
                    "query": {
                        "query_id": "query-1",
                        "query": "travel mug",
                        "candidate_count": 2,
                    },
                    "category": "loss",
                    "baseline_metric": 0.80,
                    "candidate_metric": 0.70,
                    "delta": -0.10,
                    "selection_rule": "largest deterministic loss",
                    "public_product_ids": ["p1", "p2"],
                }
            ],
        },
    }


def test_public_evidence_is_typed_bound_and_fail_closed() -> None:
    evidence = PublicEvidenceEnvelope.model_validate(public_evidence_values())
    assert evidence.run.metrics.candidate_graded_ndcg_at_10 == 0.70

    mismatched = public_evidence_values()
    mismatched["failure_analysis"]["run_id"] = "run-2"  # type: ignore[index]
    with pytest.raises(ValidationError, match="share one run_id"):
        PublicEvidenceEnvelope.model_validate(mismatched)


@pytest.mark.parametrize(
    "private_text",
    [
        "Internal artifact is s3://private-bucket/report.json.",
        "Built in AWS account 123456789012.",
        r"Loaded from C:\\private\\report.json.",
        "Loaded from C:/private/report.json.",
        "Loaded from /home/runner/report.json.",
        "Loaded from /workspace/private/report.json.",
    ],
)
def test_public_evidence_rejects_private_locators(private_text: str) -> None:
    values = public_evidence_values()
    values["run"]["limitations"] = [private_text]  # type: ignore[index]
    with pytest.raises(ValidationError, match="prohibited URI, account ID, or local path"):
        PublicEvidenceEnvelope.model_validate(values)


def test_public_evidence_rejects_unknown_log_or_uri_fields() -> None:
    values = public_evidence_values()
    values["run"]["artifact_uri"] = "private"  # type: ignore[index]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PublicEvidenceEnvelope.model_validate(values)
