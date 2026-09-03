from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from search_rank.artifacts.checksums import sha256_file
from search_rank.schemas.api import (
    PublicModelMetricRow,
    PublicValidationRunMetrics,
    PublicValidationRunSummary,
)
from search_rank.serving.app import create_app
from search_rank.serving.dependencies import ServiceSettings, ServiceState
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
