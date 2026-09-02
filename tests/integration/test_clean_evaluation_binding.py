from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from search_rank.artifacts.checksums import sha256_file
from search_rank.cli import app
from search_rank.evaluation.gates import ReleaseGateConfig, ReleaseGateInputs, evaluate_release_gate
from search_rank.evaluation.report import build_primary_metric
from search_rank.schemas.evaluation import (
    CostEvidence,
    EvaluationReport,
    MemoryResult,
    PairedDifference,
    RuntimeResult,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
IMAGE = "sha256:" + "d" * 64


def _source(root: Path, *, index: int) -> Path:
    root.mkdir()
    run_id = f"run-clean-{index}"
    report_id = f"report-clean-{index}"
    candidate_value = 0.72
    gate = evaluate_release_gate(
        ReleaseGateInputs(
            candidate_model_id="candidate-v1",
            strongest_baseline_model_id="pretrained-v1",
            candidate_ndcg_at_10=candidate_value,
            baseline_ndcg_at_10=0.70,
            difference_ci_lower=0.005,
            difference_ci_upper=0.035,
            confidence_level=0.95,
            relevance_mapping_version="project_graded_v1",
            resampling_unit="query",
            bootstrap_seed=42,
            bootstrap_resamples=10_000,
            query_count=100,
            excluded_query_count=0,
            test_access_count=index,
            clean_run_metric_values=(candidate_value,),
            candidate_lists_aligned=True,
            configuration_frozen=True,
            clean_runs_match_artifacts=True,
        ),
        ReleaseGateConfig(required_clean_runs=2),
    )
    report = EvaluationReport(
        schema_version="1.0.0",
        report_id=report_id,
        run_id=run_id,
        candidate_model_id="candidate-v1",
        baseline_model_ids=["pretrained-v1"],
        split="test",
        test_access_count=index,
        query_count=100,
        excluded_query_count=0,
        metric_definition_version="project_graded_v1",
        primary_metric=build_primary_metric(candidate_value, {"pretrained-v1": 0.70}),
        secondary_metrics={},
        paired_differences=[
            PairedDifference(
                metric_name="graded_ndcg@10",
                candidate_model_id="candidate-v1",
                baseline_model_id="pretrained-v1",
                point_estimate=0.02,
                ci_lower=0.005,
                ci_upper=0.035,
                confidence_level=0.95,
                query_count=100,
                excluded_query_count=0,
                bootstrap_seed=42,
                bootstrap_resamples=10_000,
            )
        ],
        bootstrap_method="paired_nonparametric_percentile",
        bootstrap_seed=42,
        bootstrap_resamples=10_000,
        confidence_level=0.95,
        slice_results=[],
        example_results=[],
        latency_results=[],
        memory_results=MemoryResult(
            peak_resident_memory_mb=100,
            model_artifact_size_bytes=10,
            measurement_method="fixture",
        ),
        training_runtime=RuntimeResult(
            duration_seconds=1, hardware="ml.g4dn.xlarge", measured=True
        ),
        evaluation_runtime=RuntimeResult(
            duration_seconds=1, hardware="ml.m5.xlarge", measured=True
        ),
        cost_evidence=CostEvidence(
            estimated_cost_usd=0, actual_cost_usd=None, source="not reconciled fixture"
        ),
        release_gate_results=gate,
        limitations=["fixture"],
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    report_path = root / "evaluation-report.json"
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    provenance = {
        "schema_version": "1.0.0",
        "report_id": report_id,
        "split": "test",
        "config_hash": HASH_A,
        "evaluation_config_checksum": HASH_B,
        "staged_evaluation_config_checksum": HASH_C,
        "checkpoint_checksum": HASH_C,
        "dataset_manifest_hash": HASH_A,
        "dataset_name": "tiny-esci",
        "dataset_version": "fixture-v1",
        "dataset_locale": "us",
        "strongest_baseline_id": "pretrained-v1",
        "validation_baseline_summary_checksum": HASH_B,
        "candidate_universe_hash": HASH_A,
        "system_universe_hashes": {
            "candidate-v1": HASH_A,
            "pretrained-v1": HASH_A,
        },
        "candidate_lists_aligned": True,
        "clean_run_metric_values": [candidate_value],
        "clean_ranking_hashes": [HASH_B],
        "independent_evaluation_count": 1,
        "slice_min_query_count": 50,
        "reproduction_tolerance": 0.002,
        "evaluated_baseline_model_ids": ["pretrained-v1"],
        "evaluation_image_digest": IMAGE,
        "evaluation_git_sha": "abcdef0123456789",
        "hardware_class": "ml.m5.xlarge",
        "region": "us-east-1",
        "training_strategy": "mixed_hard_random_v1",
        "test_access_count": index,
        "frozen_config": str(root / "candidate.yaml"),
    }
    provenance_path = root / "evaluation-provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    curated_path = root / "curated-queries.json"
    curated_path.write_text('{"schema_version":"1.0.0","queries":[]}\n', encoding="utf-8")
    summary = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "command": "evaluate",
        "status": "succeeded",
        "artifact_hashes": {
            "evaluation_report": f"sha256:{sha256_file(report_path)}",
            "evaluation_provenance": f"sha256:{sha256_file(provenance_path)}",
        },
        "result": {
            "candidate_model_id": "candidate-v1",
            "checkpoint": str(root / "checkpoint"),
            "checkpoint_checksum": HASH_C,
            "config_hash": HASH_A,
            "dataset_manifest_hash": HASH_A,
            "input_template_version": "enriched_v1",
            "base_model_id": "base/model",
            "base_model_revision": "233902d",
            "region": "us-east-1",
            "training_strategy": "mixed_hard_random_v1",
            "evaluation_report": str(report_path),
            "evaluation_provenance": str(provenance_path),
            "curated_queries": str(curated_path),
        },
    }
    summary_path = root / "command-summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return summary_path


def test_two_independent_evaluations_are_bound_without_test_access(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    monkeypatch.setenv("SEARCH_RANK_RUN_ROOT", str(tmp_path / "runs"))  # type: ignore[attr-defined]
    monkeypatch.setenv("SEARCH_RANK_LATEST_ROOT", str(tmp_path / "latest"))  # type: ignore[attr-defined]

    result = CliRunner().invoke(
        app,
        [
            "bind-clean-evaluations",
            "--first-summary",
            str(first),
            "--second-summary",
            str(second),
        ],
    )

    assert result.exit_code == 0, result.output
    response = json.loads(result.output.splitlines()[-1])
    summary = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    bound = EvaluationReport.model_validate_json(
        Path(summary["result"]["evaluation_report"]).read_text(encoding="utf-8")
    )
    assert bound.test_access_count == 2
    assert bound.release_gate_results.passed is True
    assert summary["result"]["clean_evaluation_count"] == 2
