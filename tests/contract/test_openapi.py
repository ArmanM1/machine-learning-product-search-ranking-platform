from __future__ import annotations

from typing import Any

from search_rank.serving.app import create_app

EXPECTED_OPERATIONS = {
    ("/healthz", "get"): "health_healthz_get",
    ("/readyz", "get"): "ready_readyz_get",
    ("/api/v1/models", "get"): "models_api_v1_models_get",
    ("/api/v1/queries", "get"): "queries_api_v1_queries_get",
    ("/api/v1/rank", "post"): "rank_api_v1_rank_post",
    ("/api/v1/comparisons/{query_id}", "get"): ("comparison_api_v1_comparisons__query_id__get"),
    ("/api/v1/runs/{run_id}", "get"): "run_summary_api_v1_runs__run_id__get",
}


def _reference(operation: dict[str, Any], status: str) -> str | None:
    schema = operation["responses"][status]["content"]["application/json"]["schema"]
    value = schema.get("$ref")
    return str(value) if value else None


def test_openapi_v1_operation_snapshot_matches_committed_contract() -> None:
    schema = create_app().openapi()
    assert schema["openapi"].startswith("3.1.")
    assert schema["info"] == {
        "title": "Machine Learning Product Search Ranking Platform",
        "version": "1.0.0",
    }
    actual = {
        (path, method): operation["operationId"]
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
    }
    assert actual == EXPECTED_OPERATIONS


def test_openapi_preserves_versioned_ranking_request_and_response_models() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/rank"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": "#/components/schemas/RankRequest"}
    assert _reference(operation, "200") == "#/components/schemas/RankResponse"

    components = schema["components"]["schemas"]
    request = components["RankRequest"]
    response = components["RankResponse"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"query_id", "model_id"}
    assert request["properties"]["top_k"]["minimum"] == 1
    assert request["properties"]["top_k"]["maximum"] == 40
    assert response["additionalProperties"] is False
    assert set(response["required"]) == {
        "request_id",
        "query_id",
        "query",
        "model_id",
        "model_artifact_checksum",
        "dataset_manifest_hash",
        "candidate_count",
        "top_k",
        "latency_ms",
        "results",
    }


def test_openapi_readiness_and_comparison_response_refs_are_stable() -> None:
    schema = create_app().openapi()
    ready = schema["paths"]["/readyz"]["get"]
    comparison = schema["paths"]["/api/v1/comparisons/{query_id}"]["get"]
    assert _reference(ready, "200") == "#/components/schemas/ReadyResponse"
    assert _reference(ready, "409") == "#/components/schemas/ApiError"
    assert _reference(comparison, "200") == "#/components/schemas/ComparisonResponse"


def test_openapi_types_curated_queries_and_complete_public_evidence() -> None:
    schema = create_app().openapi()
    query_response = schema["paths"]["/api/v1/queries"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert query_response == {
        "items": {"$ref": "#/components/schemas/CuratedQuerySummary"},
        "type": "array",
        "title": "Response Queries Api V1 Queries Get",
    }
    run = schema["paths"]["/api/v1/runs/{run_id}"]["get"]
    assert _reference(run, "200") == "#/components/schemas/PublicEvidenceEnvelope"
    assert _reference(run, "404") == "#/components/schemas/ApiError"
