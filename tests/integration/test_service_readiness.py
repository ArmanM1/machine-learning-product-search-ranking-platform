from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from search_rank.artifacts.checksums import sha256_file
from search_rank.schemas.api import (
    PublicModelMetricRow,
    PublicValidationRunMetrics,
    PublicValidationRunSummary,
)
from search_rank.serving.app import create_app
from search_rank.serving.dependencies import (
    OperationalEvidenceUnavailable,
    ServiceSettings,
    ServiceState,
)
from search_rank.serving.public_evidence import (
    build_validation_public_evidence,
    write_public_evidence,
)

pytestmark = pytest.mark.integration
ZERO_HASH = "sha256:" + "0" * 64
DATA_HASH = "sha256:" + "a" * 64
SPLIT_HASH = "sha256:" + "b" * 64


def _queries(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "queries": [
                    {
                        "query_id": "q-mug",
                        "query": "travel mug",
                        "products": [
                            {
                                "product_id": "p1",
                                "title": "Insulated travel mug",
                                "text": "Insulated travel mug steel",
                                "esci_label": "Exact",
                            },
                            {
                                "product_id": "p2",
                                "title": "Coffee beans",
                                "text": "Coffee beans dark roast",
                                "esci_label": "Irrelevant",
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _summary(
    model_id: str,
    kind: str,
    checksum: str,
    *,
    evaluation_report_id: str = "report-tiny",
    promoted: bool = True,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "display_name": model_id,
        "kind": kind,
        "base_model_id": None,
        "artifact_checksum": checksum,
        "evaluation_report_id": evaluation_report_id,
        "promoted_at": "2026-09-02T00:00:00Z" if promoted else None,
        "limitations_url": "/methodology#limitations",
    }


def _strict_validation_manifest(
    *, evaluation_report_id: str, git_sha: str = "abcdef0"
) -> dict[str, object]:
    artifact_checksums = {
        name: ZERO_HASH
        for name in (
            "baseline-summary.json",
            "curated-queries.json",
            "public-evidence.json",
            "LICENSE",
            "NOTICE",
        )
    }
    return {
        "schema_version": "1.0.0",
        "release_id": "release-validation-baseline",
        "promoted_model_id": "bm25-v1",
        "dataset_manifest_hash": DATA_HASH,
        "split_manifest_hash": SPLIT_HASH,
        "evaluation_report_id": evaluation_report_id,
        "git_sha": git_sha,
        "evidence_mode": "validation_only",
        "artifact_checksums": artifact_checksums,
        "models": [
            {
                "model_id": "bm25-v1",
                "kind": "bm25",
                "text_template": "enriched_v1",
                "artifact_checksum": ZERO_HASH,
                "public_summary": _summary(
                    "bm25-v1",
                    "bm25",
                    ZERO_HASH,
                    evaluation_report_id=evaluation_report_id,
                ),
            },
            {
                "model_id": "bm25-v2",
                "kind": "bm25",
                "text_template": "title_v1",
                "artifact_checksum": DATA_HASH,
                "public_summary": _summary(
                    "bm25-v2",
                    "bm25",
                    DATA_HASH,
                    evaluation_report_id=evaluation_report_id,
                    promoted=False,
                ),
            },
        ],
    }


def _write_release_manifest(path: Path, manifest: dict[str, object]) -> None:
    checksums = manifest["artifact_checksums"]
    assert isinstance(checksums, dict)
    for name in checksums:
        artifact = path.parent / str(name)
        if not artifact.exists():
            artifact.write_text("{}\n", encoding="utf-8")
    manifest["artifact_checksums"] = {
        str(name): f"sha256:{sha256_file(path.parent / str(name))}" for name in checksums
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_embedded_bm25_release_becomes_ready_and_ranks(tmp_path: Path) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    _queries(query_path)
    _write_release_manifest(
        manifest_path, _strict_validation_manifest(evaluation_report_id="report-tiny")
    )
    settings = ServiceSettings(
        release_manifest=manifest_path,
        curated_queries=query_path,
        web_dist=tmp_path / "absent-web-dist",
    )
    state = ServiceState(settings)
    state.load()
    assert state.ready

    with TestClient(create_app(settings, state=state)) as client:
        assert client.get("/readyz").json()["status"] == "ready"
        response = client.post(
            "/api/v1/rank",
            json={"query_id": "q-mug", "model_id": "bm25-v1", "top_k": 2},
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["product_id"] == "p1"


def test_model_load_emits_bounded_startup_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    _queries(query_path)
    _write_release_manifest(
        manifest_path, _strict_validation_manifest(evaluation_report_id="report-tiny")
    )
    events: list[tuple[str, dict[str, Any]]] = []

    def capture(_: object, event: str, **context: Any) -> None:
        events.append((event, context))

    monkeypatch.setattr("search_rank.serving.dependencies.log_event", capture)
    state = ServiceState(
        ServiceSettings(release_manifest=manifest_path, curated_queries=query_path)
    )
    state.load()
    assert state.ready
    assert state.startup_succeeded
    assert state.model_load_duration_ms is not None and state.model_load_duration_ms >= 0
    assert events == [
        (
            "service_startup_success",
            {
                "startup_success": True,
                "model_load_duration_ms": state.model_load_duration_ms,
                "model_id": "bm25-v1",
                "error_code": None,
            },
        )
    ]


def test_release_mode_requires_complete_public_evidence(tmp_path: Path) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    _queries(query_path)
    _write_release_manifest(
        manifest_path, _strict_validation_manifest(evaluation_report_id="report-tiny")
    )
    settings = ServiceSettings(
        release_manifest=manifest_path,
        curated_queries=query_path,
        release_mode=True,
        web_dist=tmp_path / "absent-web-dist",
    )
    state = ServiceState(settings)
    state.load()
    assert not state.ready

    with TestClient(create_app(settings, state=state)) as client:
        assert client.get("/readyz").status_code == 409
        assert client.get("/api/v1/queries").status_code == 409
        assert (
            client.post(
                "/api/v1/rank",
                json={"query_id": "q-mug", "model_id": "bm25-v1", "top_k": 2},
            ).status_code
            == 409
        )


def test_validation_only_baseline_evidence_is_release_ready(tmp_path: Path) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    evidence_path = tmp_path / "public-evidence.json"
    _queries(query_path)
    run = PublicValidationRunSummary(
        run_id="baseline-run-tiny",
        selected_model_id="bm25-v1",
        config_hash=ZERO_HASH,
        dataset_manifest_hash=DATA_HASH,
        split_manifest_hash=SPLIT_HASH,
        git_sha="abcdef0",
        image_digest=ZERO_HASH,
        model_artifact_checksum=ZERO_HASH,
        dataset_name="Amazon Shopping Queries ESCI",
        dataset_version="small-v1",
        locale="us",
        base_model_id=None,
        hardware_class="local-cpu",
        region="us-east-1",
        metrics=PublicValidationRunMetrics(selected_model_graded_ndcg_at_10=0.5),
        duration_seconds=1,
        actual_cost_usd=0,
        cost_evidence="Local validation execution; no AWS workload charge.",
        validation_only_notice="Baseline selected on validation before held-out access.",
        limitations=["This release contains validation-only evidence."],
        prohibited_claims=["No held-out ranking-improvement claim is allowed."],
        reproduction_command="search-rank baseline run --config baseline.yaml",
    )
    evidence = build_validation_public_evidence(
        run,
        evidence_id="baseline-summary-tiny",
        validation_query_count=10,
        excluded_query_count=0,
        models=[
            PublicModelMetricRow(
                model_id="bm25-v1",
                display_name="BM25 lexical baseline",
                kind="bm25",
                graded_ndcg_at_10=0.5,
                p95_inference_latency_ms=1,
            )
        ],
        selection_note="Selected by highest validation graded nDCG@10.",
        failure_analysis_reason="Held-out failure analysis has not been performed.",
    )
    write_public_evidence(evidence, evidence_path)
    _write_release_manifest(
        manifest_path,
        _strict_validation_manifest(evaluation_report_id="baseline-summary-tiny"),
    )
    settings = ServiceSettings(
        release_manifest=manifest_path,
        curated_queries=query_path,
        public_evidence=evidence_path,
        release_mode=True,
        web_dist=tmp_path / "absent-web-dist",
    )
    state = ServiceState(settings)
    state.load()
    assert state.ready

    with TestClient(create_app(settings, state=state)) as client:
        assert client.get("/readyz").status_code == 200
        payload = client.get("/api/v1/runs/baseline-run-tiny").json()
        assert payload["evidence_mode"] == "validation_only"
        assert payload["evaluation"]["test_access_count"] == 0
        assert payload["failure_analysis"]["status"] == "not_performed"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_sha", "abcdef9", "git SHA differs"),
        ("model_artifact_checksum", "sha256:" + "9" * 64, "model checksum differs"),
        ("split_manifest_hash", "sha256:" + "9" * 64, "split hash differs"),
    ],
)
def test_release_mode_rejects_evidence_not_bound_to_promoted_artifact(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    manifest = _strict_validation_manifest(evaluation_report_id="baseline-summary-tiny")
    run_values = {
        "run_id": "baseline-run-tiny",
        "selected_model_id": "bm25-v1",
        "config_hash": ZERO_HASH,
        "dataset_manifest_hash": DATA_HASH,
        "split_manifest_hash": SPLIT_HASH,
        "git_sha": "abcdef0",
        "image_digest": ZERO_HASH,
        "model_artifact_checksum": ZERO_HASH,
        "dataset_name": "Amazon Shopping Queries ESCI",
        "dataset_version": "small-v1",
        "locale": "us",
        "base_model_id": None,
        "hardware_class": "local-cpu",
        "region": "us-east-1",
        "metrics": {"selected_model_graded_ndcg_at_10": 0.5},
        "duration_seconds": 1,
        "actual_cost_usd": 0,
        "cost_evidence": "Local validation execution; no AWS workload charge.",
        "validation_only_notice": "Baseline selected on validation before held-out access.",
        "limitations": ["This release contains validation-only evidence."],
        "prohibited_claims": ["No held-out ranking-improvement claim is allowed."],
        "reproduction_command": "search-rank baseline run --config baseline.yaml",
    }
    run_values[field] = value
    run = PublicValidationRunSummary.model_validate(run_values)
    evidence = build_validation_public_evidence(
        run,
        evidence_id="baseline-summary-tiny",
        validation_query_count=10,
        excluded_query_count=0,
        models=[
            PublicModelMetricRow(
                model_id="bm25-v1",
                display_name="BM25 lexical baseline",
                kind="bm25",
                graded_ndcg_at_10=0.5,
            )
        ],
        selection_note="Selected by highest validation graded nDCG@10.",
        failure_analysis_reason="Held-out failure analysis has not been performed.",
    )
    with pytest.raises(ValueError, match=message):
        ServiceState._validate_evidence_binding(evidence, manifest)


def test_checksum_mismatch_never_becomes_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    (checkpoint / "weights.bin").write_bytes(b"changed")
    _queries(query_path)
    manifest = _strict_validation_manifest(evaluation_report_id="report-tiny")
    manifest["release_id"] = "release-bad"
    manifest["promoted_model_id"] = "candidate"
    manifest["models"] = [
        {
            "model_id": "candidate",
            "kind": "pretrained",
            "checkpoint": "model",
            "text_template": "enriched_v1",
            "batch_size": 32,
            "artifact_checksum": "sha256:" + "b" * 64,
            "public_summary": _summary("candidate", "pretrained", "sha256:" + "b" * 64),
        },
        {
            "model_id": "bm25-v1",
            "kind": "bm25",
            "text_template": "enriched_v1",
            "artifact_checksum": ZERO_HASH,
            "public_summary": _summary("bm25-v1", "bm25", ZERO_HASH, promoted=False),
        },
    ]
    _write_release_manifest(manifest_path, manifest)
    state = ServiceState(
        ServiceSettings(release_manifest=manifest_path, curated_queries=query_path)
    )
    failures: list[dict[str, Any]] = []

    def capture_failure(_: str, *, extra: dict[str, Any]) -> None:
        failures.append(extra["context"])

    monkeypatch.setattr("search_rank.serving.dependencies.LOGGER.exception", capture_failure)
    with pytest.raises(ValueError, match="checksum mismatch"):
        state.load()
    assert not state.ready
    assert not state.startup_succeeded
    assert failures[0]["error_code"] == "MODEL_LOAD_FAILED"
    assert failures[0]["model_load_duration_ms"] >= 0


def test_curated_query_tamper_never_becomes_ready(tmp_path: Path) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    _queries(query_path)
    _write_release_manifest(
        manifest_path, _strict_validation_manifest(evaluation_report_id="report-tiny")
    )
    query_path.write_text(query_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    state = ServiceState(
        ServiceSettings(release_manifest=manifest_path, curated_queries=query_path)
    )
    with pytest.raises(ValueError, match=r"checksum mismatch: curated-queries\.json"):
        state.load()
    assert not state.ready


def test_public_evidence_tamper_never_becomes_ready(tmp_path: Path) -> None:
    query_path = tmp_path / "curated-queries.json"
    manifest_path = tmp_path / "release-manifest.json"
    evidence_path = tmp_path / "public-evidence.json"
    _queries(query_path)
    evidence_path.write_text("{}\n", encoding="utf-8")
    _write_release_manifest(
        manifest_path, _strict_validation_manifest(evaluation_report_id="report-tiny")
    )
    evidence_path.write_text('{"tampered":true}\n', encoding="utf-8")

    state = ServiceState(
        ServiceSettings(
            release_manifest=manifest_path,
            curated_queries=query_path,
            public_evidence=evidence_path,
            release_mode=True,
        )
    )
    with pytest.raises(ValueError, match=r"checksum mismatch: public-evidence\.json"):
        state.load()
    assert not state.ready


OPERATIONS_GIT_SHA = "c" * 40


def _deployment_evidence_payload(*, code_commit: str = OPERATIONS_GIT_SHA) -> bytes:
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "deployment_evidence",
        "release_id": "release-validation-baseline",
        "model_id": "bm25-v1",
        "code_commit": code_commit,
        "serving_image_digest": "sha256:" + "d" * 64,
        "previous_lambda_version": "1",
        "production_lambda_version": "2",
        "promoted_pointer_version_id": "private-version-id",
        "smoke_tests_passed": True,
        "controlled_cold_start": {
            "schema_version": "1.0.0",
            "status": "measured",
            "measurement_class": "controlled_on_demand_lambda_cold_start",
            "controlled_cold_start": True,
            "measured_at": "2026-09-02T12:01:00Z",
            "identifiers": {
                "release_id": "release-validation-baseline",
                "model_id": "bm25-v1",
                "dataset_manifest_hash": DATA_HASH,
                "model_artifact_checksum": ZERO_HASH,
                "function_name": "private-function-name",
                "alias": "candidate",
                "function_version": "2",
                "region": "us-east-1",
            },
            "control_proof": {
                "newly_published_after_apply_started": True,
                "candidate_version_changed": True,
                "previous_candidate_version": "1",
                "new_version_prior_cloudwatch_event_count": 0,
                "on_demand_execution": True,
                "reserved_concurrency": 2,
                "provisioned_concurrency": 0,
            },
            "first_request": {
                "request_id": "private-request-id",
                "route": "/api/v1/rank",
                "http_status": 200,
                "candidate_count": 40,
                "end_to_end_latency_ms": 1000.0,
                "model_latency_ms": 100.0,
            },
            "lambda_report": {
                "init_duration_ms": 800.0,
                "invocation_duration_ms": 200.0,
                "billed_duration_ms": 1000.0,
                "configured_memory_mb": 4096,
                "max_memory_used_mb": 1000.0,
            },
            "structured_startup": {
                "startup_succeeded": True,
                "model_load_duration_ms": 700.0,
            },
            "structured_request": {"process_peak_memory_mb": 900.0},
            "sample_count": 1,
            "excluded_from_warm_samples": True,
            "limitations": ["One controlled observation is not a distribution."],
        },
        "candidate_api_gate": {
            "schema_version": "1.0.0",
            "status": "passed",
            "scope": "candidate_alias_primary_release_gate",
            "valid_request_count": 200,
            "failure_count": 0,
            "error_rate": 0.0,
            "error_rate_target": "less_than_0.01",
            "warmup_request_count": 10,
            "candidate_count": 40,
            "concurrency": 1,
            "end_to_end_latency_ms": {"p50": 100.0, "p95": 200.0, "p99": 250.0},
            "model_latency_ms": {"p50": 20.0, "p95": 40.0, "p99": 50.0},
            "lambda_memory_mb": 4096,
            "architecture": "x86_64",
            "region": "us-east-1",
            "reserved_concurrency": 2,
            "provisioned_concurrency": 0,
            "measurement_phase": "warm_after_ten_explicit_warmups",
            "controlled_cold_start_evidence_file": "candidate-cold-start.json",
            "controlled_cold_sample_included": False,
            "limitations": ["Concurrency one only."],
        },
        "production_api_smoke": {
            "schema_version": "1.0.0",
            "status": "passed",
            "scope": "bounded_release_smoke",
            "base_url_origin": "https://example.cloudfront.net",
            "model_id": "bm25-v1",
            "evaluated_candidate_model_id": "bm25-v1",
            "query_id": "q1",
            "candidate_count": 40,
            "rank_requests": 3,
            "comparison_checked": True,
            "request_count": 8,
            "error_count": 0,
            "latency_ms": {
                "minimum": 10.0,
                "median": 20.0,
                "maximum": 30.0,
                "rank_median": 25.0,
            },
            "production_error_rate_claim_eligible": False,
            "note": "Bounded smoke only.",
        },
        "browser_smoke": {"desktop": True, "mobile": True, "keyboard": True},
    }
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _mutated_deployment_evidence_payload(path: str, value: object) -> bytes:
    payload = json.loads(_deployment_evidence_payload())
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


class _FakeS3:
    def __init__(self, payload: bytes | None = None, *, error_code: str | None = None) -> None:
        self.payload = payload
        self.error_code = error_code
        self.calls: list[dict[str, object]] = []

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.error_code:
            raise ClientError(
                {"Error": {"Code": self.error_code, "Message": "not exposed"}},
                "GetObject",
            )
        assert self.payload is not None
        return {
            "Body": io.BytesIO(self.payload),
            "ContentLength": len(self.payload),
            "ContentType": "application/json",
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(self.payload).digest()).decode(),
        }


def _operations_client(s3: _FakeS3, *, lambda_version: str = "2") -> TestClient:
    settings = ServiceSettings(
        service_version=OPERATIONS_GIT_SHA,
        artifact_bucket="private-artifact-bucket",
        lambda_function_version=lambda_version,
    )
    state = ServiceState(
        settings,
        release_manifest=_strict_validation_manifest(evaluation_report_id="report-tiny"),
        s3_client=s3,
    )
    return TestClient(create_app(settings, state=state))


def test_operational_store_settings_use_the_deployed_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_BUCKET", "private-artifact-bucket")
    monkeypatch.setenv("PUBLIC_PREFIX", "public/")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_VERSION", "2")
    settings = ServiceSettings()
    assert settings.artifact_bucket == "private-artifact-bucket"
    assert settings.public_prefix == "public/"
    assert settings.lambda_function_version == "2"


@pytest.mark.parametrize("error_code", ["NoSuchKey", "AccessDenied"])
def test_operational_evidence_is_pending_until_the_canonical_record_exists(
    error_code: str,
) -> None:
    s3 = _FakeS3(error_code=error_code)
    with _operations_client(s3) as client:
        response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "schema_version": "1.0.0",
        "status": "pending",
        "release_id": "release-validation-baseline",
        "model_id": "bm25-v1",
        "note": "Deployment evidence is publishing.",
    }
    assert s3.calls == [
        {
            "Bucket": "private-artifact-bucket",
            "Key": "public/release-validation-baseline/deployment-evidence.json",
            "ChecksumMode": "ENABLED",
        }
    ]


def test_access_denied_becomes_unavailable_after_the_publication_window() -> None:
    settings = ServiceSettings(
        service_version=OPERATIONS_GIT_SHA,
        artifact_bucket="private-artifact-bucket",
        lambda_function_version="2",
    )
    state = ServiceState(
        settings,
        release_manifest=_strict_validation_manifest(evaluation_report_id="report-tiny"),
        s3_client=_FakeS3(error_code="AccessDenied"),
    )
    assert state.operational_evidence().status == "pending"
    assert state.operational_access_denied_at is not None
    state.operational_access_denied_at -= 121
    with pytest.raises(OperationalEvidenceUnavailable, match="access remained denied"):
        state.operational_evidence()


def test_operational_evidence_returns_only_the_sanitized_deployed_measurements() -> None:
    s3 = _FakeS3(_deployment_evidence_payload())
    with _operations_client(s3) as client:
        response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["status"] == "verified"
    assert payload["warm"]["candidate_count"] == 40
    assert payload["warm"]["measured_request_count"] == 200
    assert payload["warm"]["successful_request_count"] == 200
    assert payload["warm"]["end_to_end_latency_ms"]["p95"] == 200.0
    assert payload["warm"]["model_latency_ms"]["p95"] == 40.0
    assert payload["controlled_cold_start"]["excluded_from_warm_latency"] is True
    serialized = json.dumps(payload, sort_keys=True)
    for private_field in (
        "function_name",
        "function_version",
        "promoted_pointer_version_id",
        "previous_lambda_version",
        "production_lambda_version",
        "private-request-id",
    ):
        assert private_field not in serialized


def test_stale_deployment_record_is_pending_during_a_new_activation() -> None:
    s3 = _FakeS3(_deployment_evidence_payload(code_commit="e" * 40))
    with _operations_client(s3) as client:
        response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_evidence_for_another_lambda_version_is_pending_during_activation() -> None:
    payload = json.loads(_deployment_evidence_payload())
    payload["production_lambda_version"] = "3"
    payload["controlled_cold_start"]["identifiers"]["function_version"] = "3"
    s3 = _FakeS3((json.dumps(payload, sort_keys=True) + "\n").encode())
    with _operations_client(s3, lambda_version="2") as client:
        response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("controlled_cold_start.identifiers.dataset_manifest_hash", "sha256:" + "9" * 64),
        ("controlled_cold_start.identifiers.model_artifact_checksum", "sha256:" + "8" * 64),
        ("controlled_cold_start.first_request.candidate_count", 20),
        ("production_api_smoke.candidate_count", 20),
        ("controlled_cold_start.control_proof.reserved_concurrency", 1),
        ("controlled_cold_start.control_proof.provisioned_concurrency", 1),
        ("controlled_cold_start.lambda_report.configured_memory_mb", 2048),
        ("controlled_cold_start.identifiers.region", "us-west-2"),
    ],
)
def test_operational_evidence_rejects_cross_bound_identity_or_configuration(
    path: str,
    value: object,
) -> None:
    with _operations_client(_FakeS3(_mutated_deployment_evidence_payload(path, value))) as client:
        response = client.get("/api/v1/operations")
    assert response.status_code == 409
    assert response.json()["code"] == "operational_evidence_conflict"


def test_release_mode_requires_operational_store_and_lambda_identity() -> None:
    manifest = _strict_validation_manifest(evaluation_report_id="report-tiny")
    missing_store = ServiceSettings(
        service_version=OPERATIONS_GIT_SHA,
        release_mode=True,
        lambda_function_version="2",
    )
    state = ServiceState(missing_store, release_manifest=manifest)
    with TestClient(create_app(missing_store, state=state)) as client:
        assert client.get("/api/v1/operations").status_code == 503

    missing_version = ServiceSettings(
        service_version=OPERATIONS_GIT_SHA,
        release_mode=True,
        artifact_bucket="private-artifact-bucket",
    )
    state = ServiceState(missing_version, release_manifest=manifest, s3_client=_FakeS3())
    with TestClient(create_app(missing_version, state=state)) as client:
        assert client.get("/api/v1/operations").status_code == 503


def test_operational_transport_failures_are_mapped_to_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenBody:
        def read(self, _: int) -> bytes:
            raise OSError("private transport failure")

        def close(self) -> None:
            return None

    class BrokenReadS3(_FakeS3):
        def get_object(self, **kwargs: object) -> dict[str, object]:
            response = super().get_object(**kwargs)
            response["Body"] = BrokenBody()
            return response

    with _operations_client(BrokenReadS3(_deployment_evidence_payload())) as client:
        assert client.get("/api/v1/operations").status_code == 503

    monkeypatch.setattr(
        "search_rank.serving.dependencies.boto3.client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("client unavailable")),
    )
    settings = ServiceSettings(
        service_version=OPERATIONS_GIT_SHA,
        artifact_bucket="private-artifact-bucket",
        lambda_function_version="2",
    )
    state = ServiceState(
        settings,
        release_manifest=_strict_validation_manifest(evaluation_report_id="report-tiny"),
    )
    with TestClient(create_app(settings, state=state)) as client:
        assert client.get("/api/v1/operations").status_code == 503


def test_operational_evidence_rejects_tamper_and_hides_store_failures() -> None:
    bad_checksum = _FakeS3(_deployment_evidence_payload())
    original_get = bad_checksum.get_object

    def tampered_get(**kwargs: object) -> dict[str, object]:
        response = original_get(**kwargs)
        response["ChecksumSHA256"] = "not-the-object-checksum"
        return response

    bad_checksum.get_object = tampered_get  # type: ignore[method-assign]
    with _operations_client(bad_checksum) as client:
        conflict = client.get("/api/v1/operations")
    assert conflict.status_code == 409
    assert conflict.headers["cache-control"] == "no-store"
    assert conflict.json()["code"] == "operational_evidence_conflict"

    with _operations_client(_FakeS3(error_code="SlowDown")) as client:
        unavailable = client.get("/api/v1/operations")
    assert unavailable.status_code == 503
    assert unavailable.headers["cache-control"] == "no-store"
    assert unavailable.json()["code"] == "operational_evidence_unavailable"
