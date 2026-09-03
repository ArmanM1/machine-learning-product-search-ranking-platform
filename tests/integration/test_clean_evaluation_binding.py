from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from search_rank.artifacts.checksums import sha256_file
from search_rank.cli import app
from search_rank.evaluation.gates import ReleaseGateConfig, ReleaseGateInputs, evaluate_release_gate
from search_rank.evaluation.report import build_primary_metric
from search_rank.schemas.evaluation import (
    CostEvidence,
    EvaluationReport,
    ExampleResult,
    MemoryResult,
    PairedDifference,
    RuntimeResult,
)
from search_rank.schemas.evidence import EvaluationProvenance

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
IMAGE = "sha256:" + "d" * 64
GIT_SHA = "a" * 40


def _heldout_examples() -> list[ExampleResult]:
    examples = [
        ExampleResult(
            query_id=f"win-{index}",
            category="win",
            baseline_metric=0.6,
            candidate_metric=0.7 + index * 0.001,
            delta=0.1 + index * 0.001,
            selection_rule="fixture deterministic win",
        )
        for index in range(5)
    ]
    examples.extend(
        ExampleResult(
            query_id=f"loss-{index}",
            category="loss",
            baseline_metric=0.7,
            candidate_metric=0.6 - index * 0.001,
            delta=-0.1 - index * 0.001,
            selection_rule="fixture deterministic loss",
        )
        for index in range(5)
    )
    examples.extend(
        ExampleResult(
            query_id=f"tie-{index}",
            category="tie_or_uncertain",
            baseline_metric=0.65,
            candidate_metric=0.65,
            delta=0,
            selection_rule="fixture deterministic tie",
        )
        for index in range(3)
    )
    examples.extend(
        [
            ExampleResult(
                query_id="lexical",
                category="lexical_preferred",
                baseline_metric=0.8,
                candidate_metric=0.6,
                delta=-0.2,
                selection_rule="fixture lexical preference",
            ),
            ExampleResult(
                query_id="confusion",
                category="complement_exact_confusion",
                baseline_metric=0.7,
                candidate_metric=0.5,
                delta=-0.2,
                selection_rule="fixture Complement-versus-Exact confusion",
            ),
        ]
    )
    return examples


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
        example_results=_heldout_examples(),
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
        "artifact_type": "evaluation_provenance",
        "report_id": report_id,
        "split": "test",
        "config_hash": HASH_A,
        "evaluation_config_checksum": HASH_B,
        "staged_evaluation_config_checksum": HASH_C,
        "checkpoint_checksum": HASH_C,
        "dataset_manifest_hash": HASH_A,
        "split_manifest_hash": HASH_D,
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
        "evaluation_git_sha": GIT_SHA,
        "hardware_class": "ml.m5.xlarge",
        "region": "us-east-1",
        "training_strategy": "mixed_hard_random_v1",
        "test_access_count": index,
        "frozen_config": str(root / "candidate.yaml"),
        "source_evaluations": [],
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
        "config_path": "configs/experiments/release-v1.yaml",
        "started_at": "2026-09-02T00:00:00Z",
        "ended_at": "2026-09-02T00:01:00Z",
        "duration_seconds": 60,
        "git_sha": GIT_SHA,
        "repository_dirty": False,
        "runtime": {"python": "3.11", "platform": "fixture"},
        "artifact_paths": {
            "evaluation_report": str(report_path),
            "evaluation_provenance": str(provenance_path),
            "curated_queries": str(curated_path),
        },
        "artifact_hashes": {
            "evaluation_report": f"sha256:{sha256_file(report_path)}",
            "evaluation_provenance": f"sha256:{sha256_file(provenance_path)}",
            "curated_queries": f"sha256:{sha256_file(curated_path)}",
        },
        "failure": None,
        "result": {
            "candidate_model_id": "candidate-v1",
            "checkpoint": str(root / "checkpoint"),
            "checkpoint_checksum": HASH_C,
            "config_hash": HASH_A,
            "dataset_manifest_hash": HASH_A,
            "split_manifest_hash": HASH_D,
            "evaluation_config_checksum": HASH_B,
            "evaluation_image_digest": IMAGE,
            "evaluation_git_sha": GIT_SHA,
            "hardware_class": "ml.m5.xlarge",
            "input_template_version": "enriched_v1",
            "base_model_id": "base/model",
            "base_model_revision": "233902d",
            "region": "us-east-1",
            "training_strategy": "mixed_hard_random_v1",
            "primary_metric": report.primary_metric.model_dump(mode="json"),
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


def test_clean_evaluation_binding_rejects_incomplete_heldout_examples(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    first_summary = json.loads(first.read_text(encoding="utf-8"))
    report_path = Path(first_summary["result"]["evaluation_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["example_results"] = []
    report_path.write_text(json.dumps(report), encoding="utf-8")
    first_summary["artifact_hashes"]["evaluation_report"] = f"sha256:{sha256_file(report_path)}"
    first.write_text(json.dumps(first_summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "held-out representative-example requirements are incomplete" in failure["failure"]


def test_clean_evaluation_binding_rejects_different_candidate_rankings(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    second_summary = json.loads(second.read_text(encoding="utf-8"))
    provenance_path = Path(second_summary["result"]["evaluation_provenance"])
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["clean_ranking_hashes"] = [HASH_C]
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    second_summary["artifact_hashes"]["evaluation_provenance"] = (
        f"sha256:{sha256_file(provenance_path)}"
    )
    second.write_text(json.dumps(second_summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "different candidate ranking hashes" in failure["failure"]


def test_clean_evaluation_binding_rejects_different_split_manifests(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    second_summary = json.loads(second.read_text(encoding="utf-8"))
    provenance_path = Path(second_summary["result"]["evaluation_provenance"])
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["split_manifest_hash"] = HASH_C
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    second_summary["result"]["split_manifest_hash"] = HASH_C
    second_summary["artifact_hashes"]["evaluation_provenance"] = (
        f"sha256:{sha256_file(provenance_path)}"
    )
    second.write_text(json.dumps(second_summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "immutable identity: split_manifest_hash" in failure["failure"]


def test_clean_evaluation_binding_rejects_different_primary_baseline_evidence(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    second_summary = json.loads(second.read_text(encoding="utf-8"))
    report_path = Path(second_summary["result"]["evaluation_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["primary_metric"]["baseline_values"]["pretrained-v1"] = 0.69
    report["primary_metric"]["strongest_baseline_value"] = 0.69
    report["primary_metric"]["candidate_minus_baseline"] = 0.03
    report["paired_differences"][0]["point_estimate"] = 0.03
    second_summary["result"]["primary_metric"] = report["primary_metric"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    second_summary["artifact_hashes"]["evaluation_report"] = f"sha256:{sha256_file(report_path)}"
    second.write_text(json.dumps(second_summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "frozen identity: primary_metric" in failure["failure"]


def test_clean_evaluation_binding_rejects_different_paired_interval_evidence(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    second_summary = json.loads(second.read_text(encoding="utf-8"))
    report_path = Path(second_summary["result"]["evaluation_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["paired_differences"][0]["ci_lower"] = 0.006
    report_path.write_text(json.dumps(report), encoding="utf-8")
    second_summary["artifact_hashes"]["evaluation_report"] = f"sha256:{sha256_file(report_path)}"
    second.write_text(json.dumps(second_summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "paired-difference evidence" in failure["failure"]


def test_clean_evaluation_binding_rejects_falsified_slice_adequacy(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    falsified_slice = {
        "dimension": "query_frequency",
        "slice_name": "head",
        "query_count": 50,
        "excluded_query_count": 0,
        "candidate_value": 0.60,
        "baseline_value": 0.65,
        "point_estimate": -0.05,
        "ci_lower": -0.08,
        "ci_upper": -0.02,
        "adequate_sample_size": False,
        "finding": "insufficient_data",
    }
    for summary_path in (first, second):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        report_path = Path(summary["result"]["evaluation_report"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["slice_results"] = [falsified_slice]
        report_path.write_text(json.dumps(report), encoding="utf-8")
        summary["artifact_hashes"]["evaluation_report"] = f"sha256:{sha256_file(report_path)}"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "slice adequacy is inconsistent" in failure["failure"]


def test_clean_evaluation_binding_rejects_different_frozen_summary_identity(
    tmp_path: Path, monkeypatch: object
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    second_summary = json.loads(second.read_text(encoding="utf-8"))
    second_summary["result"]["base_model_revision"] = "different-revision"
    second.write_text(json.dumps(second_summary), encoding="utf-8")
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

    assert result.exit_code == 1
    response = json.loads(result.output.splitlines()[-1])
    failure = json.loads(Path(response["summary"]).read_text(encoding="utf-8"))
    assert "frozen identity: base_model_revision" in failure["failure"]


def test_bound_provenance_contract_rejects_different_candidate_rankings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _source(tmp_path / "first", index=1)
    second = _source(tmp_path / "second", index=2)
    monkeypatch.setenv("SEARCH_RANK_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("SEARCH_RANK_LATEST_ROOT", str(tmp_path / "latest"))
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
    provenance_path = Path(summary["result"]["evaluation_provenance"])
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["clean_ranking_hashes"][1] = HASH_C
    provenance["source_evaluations"][1]["candidate_ranking_hash"] = HASH_C

    with pytest.raises(ValidationError, match="identical candidate rankings"):
        EvaluationProvenance.model_validate(provenance)
