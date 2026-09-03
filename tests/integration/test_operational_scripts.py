from __future__ import annotations

import importlib
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from search_rank.artifacts.checksums import sha256_file
from search_rank.config import sha256_value
from search_rank.schemas.api import (
    PublicModelMetricRow,
    PublicValidationRunMetrics,
    PublicValidationRunSummary,
)
from search_rank.serving.public_evidence import (
    build_validation_public_evidence,
    write_public_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
container_eval = importlib.import_module("scripts.container_eval")
container_train = importlib.import_module("scripts.container_train")
estimate_cloud_cost = importlib.import_module("scripts.estimate_cloud_cost")
smoke_test = importlib.import_module("scripts.smoke_test")
verify_release = importlib.import_module("scripts.verify_release")
validate_release_artifacts = importlib.import_module("scripts.validate_release_artifacts")
validate_training_contracts = importlib.import_module("scripts.validate_training_contracts")

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("sage_maker_argv", [[], ["train"]])
def test_training_entrypoint_bundles_frozen_config(
    tmp_path: Path, sage_maker_argv: list[str]
) -> None:
    config = tmp_path / "candidate.yaml"
    manifest = tmp_path / "manifest.json"
    model_dir = tmp_path / "model"
    config.write_text("schema_version: 1.0.0\n", encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    command, selected_output = container_train.build_command(
        [
            *sage_maker_argv,
            "--config",
            str(config),
            "--dataset-manifest",
            str(manifest),
            "--model-dir",
            str(model_dir),
        ]
    )
    bundled = model_dir / "frozen-experiment.yaml"
    assert bundled.read_bytes() == config.read_bytes()
    assert command[-2:] == ["--dataset-manifest", str(manifest.resolve())]
    assert str(bundled) in command
    assert selected_output == model_dir.resolve()


def test_training_entrypoint_rejects_non_sagemaker_program_argument() -> None:
    with pytest.raises(SystemExit):
        container_train.build_command(["serve"])


def test_training_dispatch_requires_the_frozen_requested_hardware() -> None:
    config = ROOT / "configs" / "experiments" / "candidate-v1.yaml"
    validated = validate_training_contracts.validate_config(
        config,
        instance_type="ml.g4dn.xlarge",
        accelerator="gpu",
    )
    assert validated.requested_hardware == "ml.g4dn.xlarge"
    with pytest.raises(ValueError, match="requested_hardware"):
        validate_training_contracts.validate_config(
            config,
            instance_type="ml.m5.xlarge",
            accelerator="cpu",
        )


def test_evaluation_entrypoint_refuses_unapproved_heldout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "release.yaml"
    config.write_text("schema_version: 1.0.0\nsplit: test\n", encoding="utf-8")
    monkeypatch.delenv("ALLOW_HELDOUT_EVAL", raising=False)
    with pytest.raises(ValueError, match="ALLOW_HELDOUT_EVAL=1"):
        container_eval.build_command(["--config", str(config), "--heldout"])


def test_cost_estimate_passes_only_inside_zero_spend_and_credit_guards() -> None:
    parser = estimate_cloud_cost._parser()
    args = parser.parse_args(
        [
            "--unit-price-usd",
            "0.75",
            "--run-kind",
            "development",
            "--accelerator",
            "gpu",
            "--runtime-seconds",
            "3600",
            "--declared-job-cost-cap-usd",
            "1.00",
            "--campaign-spend-to-date-usd",
            "0",
            "--remaining-applicable-credit-usd",
            "100",
            "--estimated-remaining-non-job-usd",
            "10",
        ]
    )
    report, passed = estimate_cloud_cost.estimate(args)
    assert passed
    assert report["maximum_job_estimate_usd"] == "0.75"
    assert report["maximum_out_of_pocket_usd"] == "0"
    assert report["aws_calls_performed"] == 0

    args.remaining_applicable_credit_usd = "40"
    refused, passed = estimate_cloud_cost.estimate(args)
    assert not passed
    assert refused["status"] == "refused"
    assert any("credit" in error for error in refused["errors"])


def test_smoke_script_exercises_primary_flow_without_error_rate_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(
        _base_url: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[Any, float]:
        if path == "/healthz":
            return {"status": "ok", "service_version": "test"}, 1.0
        if path == "/readyz":
            return {"status": "ready", "model_id": "candidate"}, 2.0
        if path == "/api/v1/models":
            return [
                {"model_id": "baseline", "kind": "pretrained"},
                {"model_id": "candidate", "kind": "fine_tuned"},
            ], 3.0
        if path == "/api/v1/queries?limit=1":
            return [{"query_id": "q1", "candidate_count": 2}], 4.0
        if path == "/api/v1/rank":
            assert payload == {"query_id": "q1", "model_id": "candidate", "top_k": 2}
            return {"results": [{}, {}]}, 5.0
        if path.startswith("/api/v1/comparisons/q1?"):
            return {
                "baseline_model_id": "baseline",
                "candidate_model_id": "candidate",
            }, 6.0
        raise AssertionError(path)

    monkeypatch.setattr(smoke_test, "_request", fake_request)
    report = smoke_test.run_smoke("https://demo.example.test", repeat=2)
    assert report["status"] == "passed"
    assert report["comparison_checked"] is True
    assert report["evaluated_candidate_model_id"] == "candidate"
    assert report["production_error_rate_claim_eligible"] is False


def test_smoke_script_keeps_failed_candidate_distinct_from_active_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_comparison: dict[str, str] = {}

    def fake_request(
        _base_url: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[Any, float]:
        if path == "/healthz":
            return {"status": "ok", "service_version": "test"}, 1.0
        if path == "/readyz":
            return {"status": "ready", "model_id": "baseline"}, 2.0
        if path == "/api/v1/models":
            return [
                {"model_id": "baseline", "kind": "pretrained"},
                {"model_id": "failed-candidate", "kind": "fine_tuned"},
            ], 3.0
        if path == "/api/v1/queries?limit=1":
            return [{"query_id": "q1", "candidate_count": 2}], 4.0
        if path == "/api/v1/rank":
            assert payload == {"query_id": "q1", "model_id": "baseline", "top_k": 2}
            return {"results": [{}, {}]}, 5.0
        if path.startswith("/api/v1/comparisons/q1?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            requested_comparison.update({key: values[0] for key, values in query.items()})
            return {
                "baseline_model_id": "baseline",
                "candidate_model_id": "failed-candidate",
            }, 6.0
        raise AssertionError(path)

    monkeypatch.setattr(smoke_test, "_request", fake_request)
    report = smoke_test.run_smoke("https://demo.example.test", repeat=1)

    assert report["model_id"] == "baseline"
    assert report["evaluated_candidate_model_id"] == "failed-candidate"
    assert report["comparison_checked"] is True
    assert requested_comparison == {
        "baseline": "baseline",
        "candidate": "failed-candidate",
        "include_judgments": "true",
    }


def test_release_verifier_accepts_exact_validation_bundle_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    data_hash = "sha256:" + "a" * 64
    image_hash = "sha256:" + "b" * 64
    split_hash = "sha256:" + "c" * 64
    model_ids = ("bm25-title-v1", "bm25-enriched-v1")
    checksums = {
        model_id: f"sha256:{sha256_value({'model_id': model_id})}" for model_id in model_ids
    }
    (tmp_path / "curated-queries.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "queries": [
                    {
                        "query_id": "q1",
                        "query": "travel mug",
                        "products": [
                            {
                                "product_id": "p1",
                                "title": "Insulated mug",
                                "text": "Insulated travel mug",
                                "esci_label": "Exact",
                            }
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "baseline-summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "config_hash": "sha256:" + "c" * 64,
                "dataset_manifest_hash": data_hash,
                "dataset_name": "Amazon Shopping Queries ESCI",
                "dataset_version": "small-v1",
                "dataset_locale": "us",
                "split": "validation",
                "metrics": {model_ids[0]: 0.5, model_ids[1]: 0.4},
                "system_metrics": {
                    model_ids[0]: {"graded_ndcg@10": 0.5},
                    model_ids[1]: {"graded_ndcg@10": 0.4},
                },
                "system_metric_query_counts": {
                    model_ids[0]: {"graded_ndcg@10": 1},
                    model_ids[1]: {"graded_ndcg@10": 1},
                },
                "system_metric_excluded_query_counts": {
                    model_ids[0]: {"graded_ndcg@10": 0},
                    model_ids[1]: {"graded_ndcg@10": 0},
                },
                "p95_inference_latency_ms": {model_ids[0]: 1, model_ids[1]: 1},
                "strongest_baseline_id": model_ids[0],
                "strongest_baseline_value": 0.5,
                "validation_query_count": 1,
                "excluded_query_count": 0,
                "rankings": {model_ids[0]: "rankings-a.jsonl", model_ids[1]: "rankings-b.jsonl"},
                "resumed_from_run_id": None,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    run = PublicValidationRunSummary(
        run_id="baseline-run-1",
        selected_model_id=model_ids[0],
        config_hash="sha256:" + "c" * 64,
        dataset_manifest_hash=data_hash,
        split_manifest_hash=split_hash,
        git_sha="abcdef0",
        image_digest=image_hash,
        model_artifact_checksum=checksums[model_ids[0]],
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
        validation_only_notice="Validation evidence only; held-out data was not opened.",
        limitations=["This is validation-only evidence."],
        prohibited_claims=["No held-out improvement claim is allowed."],
        reproduction_command="python -m search_rank.cli baseline run --config baseline.yaml",
    )
    evidence = build_validation_public_evidence(
        run,
        evidence_id="validation-baseline-run-1",
        validation_query_count=1,
        excluded_query_count=0,
        models=[
            PublicModelMetricRow(
                model_id=model_id,
                display_name=model_id,
                kind="bm25",
                graded_ndcg_at_10=value,
                p95_inference_latency_ms=1,
            )
            for model_id, value in zip(model_ids, (0.5, 0.4), strict=True)
        ],
        selection_note="Selected on validation graded nDCG@10.",
        failure_analysis_reason="Held-out failure analysis was not performed.",
    )
    write_public_evidence(evidence, tmp_path / "public-evidence.json")
    for name in ("LICENSE", "NOTICE"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    artifact_names = (
        "baseline-summary.json",
        "curated-queries.json",
        "public-evidence.json",
        "LICENSE",
        "NOTICE",
    )
    manifest = {
        "schema_version": "1.0.0",
        "release_id": "baseline-run-1",
        "promoted_model_id": model_ids[0],
        "dataset_manifest_hash": data_hash,
        "split_manifest_hash": split_hash,
        "evaluation_report_id": "validation-baseline-run-1",
        "git_sha": "abcdef0",
        "evidence_mode": "validation_only",
        "artifact_checksums": {
            name: "sha256:" + sha256_file(tmp_path / name) for name in artifact_names
        },
        "models": [
            {
                "model_id": model_id,
                "kind": "bm25",
                "text_template": "title_v1" if "title" in model_id else "enriched_v1",
                "artifact_checksum": checksums[model_id],
                "public_summary": {
                    "model_id": model_id,
                    "display_name": model_id,
                    "kind": "bm25",
                    "base_model_id": None,
                    "artifact_checksum": checksums[model_id],
                    "evaluation_report_id": "validation-baseline-run-1",
                    "promoted_at": ("2026-09-02T00:00:00Z" if model_id == model_ids[0] else None),
                    "limitations_url": "/methodology#limitations",
                },
            }
            for model_id in model_ids
        ],
    }
    (tmp_path / "release-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = {
        path.relative_to(tmp_path).as_posix(): "sha256:" + sha256_file(path)
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file() and path.name != "bundle-checksums.json"
    }
    (tmp_path / "bundle-checksums.json").write_text(
        json.dumps({"schema_version": "1.0.0", "files": files}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = verify_release.verify_release(tmp_path, load_models=False)
    assert result["status"] == "passed"
    assert result["evidence_mode"] == "validation_only"
    assert result["split_manifest_hash"] == split_hash
    validate_release_artifacts.validate_bundle(tmp_path)

    with (tmp_path / "public-evidence.json").open("a", encoding="utf-8") as handle:
        handle.write(" \n")
    with pytest.raises(ValueError, match="artifact checksum mismatch"):
        verify_release.verify_release(tmp_path, load_models=False)
