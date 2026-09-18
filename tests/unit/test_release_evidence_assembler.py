from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from scripts import assemble_release_evidence as assembler
from tests.unit.test_durable_evidence_contracts import (
    FINANCIAL_SNAPSHOT,
)
from tests.unit.test_durable_evidence_contracts import (
    candidate_gate as valid_candidate_gate,
)
from tests.unit.test_durable_evidence_contracts import (
    cold_start as valid_cold_start,
)
from tests.unit.test_durable_evidence_contracts import (
    performance_report as valid_performance_report,
)
from tests.unit.test_durable_evidence_contracts import (
    smoke as valid_smoke,
)

SOURCE_SHA = "a" * 40
MODEL_SOURCE_SHA = "d" * 40
DEPLOYMENT_SHA = "b" * 40
BASELINE_SHA = "c" * 40
DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64
DIGEST_C = "sha256:" + "3" * 64
DIGEST_D = "sha256:" + "4" * 64
RANKING_DIGEST = "sha256:" + "5" * 64
ORIGIN = "https://resume-demo.cloudfront.net"
BENCHMARK_RUN_ID = "github-2002-attempt-1"
BASELINE_RELEASE = "baseline-release"
BASELINE_MODEL = "baseline-model"
CANDIDATE_MODEL = "candidate-model"
VERIFIED_RELEASE = "verified-release"
TRIAL_ID = "trial-selection-0123456789abcdefabcd"


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def _base(stage: str, sha: str, run_id: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "stage": stage,
        "frozen_git_sha": sha,
        "github_run_id": str(run_id),
    }


def _stage(root: Path, sha: str, stage: str, handoff: dict[str, Any]) -> Path:
    stage_root = root / sha / stage
    _write(stage_root / "_handoff.json", handoff)
    return stage_root


def _heldout_examples() -> list[dict[str, Any]]:
    examples = [
        {
            "query_id": f"win-{index}",
            "category": "win",
            "baseline_metric": 0.6,
            "candidate_metric": 0.7 + index * 0.001,
            "delta": 0.1 + index * 0.001,
            "selection_rule": "deterministic fixture win",
        }
        for index in range(5)
    ]
    examples.extend(
        {
            "query_id": f"loss-{index}",
            "category": "loss",
            "baseline_metric": 0.7,
            "candidate_metric": 0.6 - index * 0.001,
            "delta": -0.1 - index * 0.001,
            "selection_rule": "deterministic fixture loss",
        }
        for index in range(5)
    )
    examples.extend(
        {
            "query_id": f"tie-{index}",
            "category": "tie_or_uncertain",
            "baseline_metric": 0.65,
            "candidate_metric": 0.65,
            "delta": 0.0,
            "selection_rule": "deterministic fixture tie",
        }
        for index in range(3)
    )
    examples.extend(
        [
            {
                "query_id": "lexical",
                "category": "lexical_preferred",
                "baseline_metric": 0.8,
                "candidate_metric": 0.6,
                "delta": -0.2,
                "selection_rule": "deterministic lexical case",
            },
            {
                "query_id": "confusion",
                "category": "complement_exact_confusion",
                "baseline_metric": 0.7,
                "candidate_metric": 0.5,
                "delta": -0.2,
                "selection_rule": "deterministic complement case",
            },
        ]
    )
    return examples


def _source_evaluations(candidate_value: float) -> list[dict[str, Any]]:
    return [
        {
            "run_id": f"clean-run-{index}",
            "report_id": f"clean-report-{index}",
            "report_checksum": DIGEST_A,
            "provenance_checksum": DIGEST_B,
            "test_access_count": index,
            "candidate_metric": candidate_value,
            "candidate_ranking_hash": RANKING_DIGEST,
        }
        for index in (1, 2)
    ]


def _evaluation_report(gate_passed: bool) -> dict[str, Any]:
    candidate_value = 0.72 if gate_passed else 0.66
    baseline_value = 0.68
    difference = candidate_value - baseline_value
    promoted_model = CANDIDATE_MODEL if gate_passed else BASELINE_MODEL
    interval = (0.01, 0.07) if gate_passed else (-0.05, 0.01)
    return {
        "schema_version": "1.0.0",
        "report_id": VERIFIED_RELEASE,
        "run_id": "heldout-run",
        "candidate_model_id": CANDIDATE_MODEL,
        "baseline_model_ids": [BASELINE_MODEL],
        "split": "test",
        "test_access_count": 2,
        "query_count": 100,
        "excluded_query_count": 0,
        "metric_definition_version": "project_graded_v1",
        "primary_metric": {
            "metric_name": "graded_ndcg@10",
            "candidate_value": candidate_value,
            "baseline_values": {BASELINE_MODEL: baseline_value},
            "strongest_baseline_id": BASELINE_MODEL,
            "strongest_baseline_value": baseline_value,
            "candidate_minus_baseline": difference,
        },
        "secondary_metrics": {},
        "system_metrics": {},
        "paired_differences": [
            {
                "metric_name": "graded_ndcg@10",
                "candidate_model_id": CANDIDATE_MODEL,
                "baseline_model_id": BASELINE_MODEL,
                "point_estimate": difference,
                "ci_lower": interval[0],
                "ci_upper": interval[1],
                "confidence_level": 0.95,
                "query_count": 100,
                "excluded_query_count": 0,
                "bootstrap_seed": 42,
                "bootstrap_resamples": 10_000,
                "resampling_unit": "query",
            }
        ],
        "bootstrap_method": "paired_nonparametric_percentile",
        "bootstrap_seed": 42,
        "bootstrap_resamples": 10_000,
        "confidence_level": 0.95,
        "slice_results": [],
        "example_results": _heldout_examples(),
        "latency_results": [],
        "memory_results": {
            "peak_resident_memory_mb": 512.0,
            "model_artifact_size_bytes": 1024,
            "measurement_method": "fixture measurement",
        },
        "training_runtime": {
            "duration_seconds": 60.0,
            "hardware": "ml.g4dn.xlarge",
            "measured": True,
        },
        "evaluation_runtime": {
            "duration_seconds": 30.0,
            "hardware": "ml.m5.xlarge",
            "measured": True,
        },
        "cost_evidence": {
            "estimated_cost_usd": 0.25,
            "actual_cost_usd": None,
            "source": "fixture estimate",
            "currency": "USD",
        },
        "release_gate_results": {
            "passed": gate_passed,
            "decision": "promote_candidate" if gate_passed else "retain_baseline",
            "candidate_model_id": CANDIDATE_MODEL,
            "baseline_model_id": BASELINE_MODEL,
            "promoted_model_id": promoted_model,
            "positive_claim_allowed": gate_passed,
            "negative_result_required": not gate_passed,
            "checks": [
                {
                    "name": "paired heldout comparison",
                    "passed": gate_passed,
                    "detail": "fixture gate result",
                }
            ],
            "reasons": ["heldout gate passed" if gate_passed else "heldout gate failed"],
        },
        "limitations": ["Synthetic contract fixture."],
        "created_at": "2026-09-02T11:00:00Z",
    }


def _evaluation_provenance(report: dict[str, Any]) -> dict[str, Any]:
    candidate_value = report["primary_metric"]["candidate_value"]
    return {
        "schema_version": "1.0.0",
        "artifact_type": "evaluation_provenance",
        "report_id": VERIFIED_RELEASE,
        "split": "test",
        "config_hash": DIGEST_D,
        "evaluation_config_checksum": DIGEST_A,
        "staged_evaluation_config_checksum": DIGEST_A,
        "evaluation_image_digest": DIGEST_B,
        "evaluation_git_sha": SOURCE_SHA,
        "hardware_class": "ml.m5.xlarge",
        "region": "us-east-1",
        "training_strategy": "mixed_hard_random_v1",
        "frozen_config": "immutable evaluation config",
        "checkpoint_checksum": DIGEST_B,
        "dataset_manifest_hash": DIGEST_A,
        "split_manifest_hash": DIGEST_C,
        "dataset_name": "tiny-esci",
        "dataset_version": "fixture-v1",
        "dataset_locale": "us",
        "strongest_baseline_id": BASELINE_MODEL,
        "validation_baseline_summary_checksum": DIGEST_D,
        "candidate_universe_hash": DIGEST_A,
        "system_universe_hashes": {CANDIDATE_MODEL: DIGEST_A, BASELINE_MODEL: DIGEST_A},
        "candidate_lists_aligned": True,
        "clean_run_metric_values": [candidate_value, candidate_value],
        "clean_ranking_hashes": [RANKING_DIGEST, RANKING_DIGEST],
        "independent_evaluation_count": 2,
        "slice_min_query_count": 50,
        "reproduction_tolerance": 0.002,
        "evaluated_baseline_model_ids": [BASELINE_MODEL],
        "test_access_count": 2,
        "source_evaluations": _source_evaluations(candidate_value),
    }


def _release_summary(report: dict[str, Any]) -> dict[str, Any]:
    gate = report["release_gate_results"]
    candidate_value = report["primary_metric"]["candidate_value"]
    return {
        "schema_version": "1.0.0",
        "artifact_type": "heldout_release_summary",
        "report_id": VERIFIED_RELEASE,
        "run_id": report["run_id"],
        "candidate_model_id": CANDIDATE_MODEL,
        "baseline_model_ids": [BASELINE_MODEL],
        "promoted_model_id": gate["promoted_model_id"],
        "promotion_decision": gate["decision"],
        "gate_passed": gate["passed"],
        "test_access_count": 2,
        "clean_evaluation_count": 2,
        "source_evaluations": _source_evaluations(candidate_value),
        "primary_metric": report["primary_metric"],
        "paired_differences": report["paired_differences"],
        "code_commit": SOURCE_SHA,
        "evaluation_image_digest": DIGEST_B,
        "evaluation_config_hash": DIGEST_A,
        "trial_selection_id": TRIAL_ID,
        "trial_selection_sha256": DIGEST_C,
    }


def _portfolio_ablations() -> dict[str, Any]:
    treatment_value = 0.72
    controls = {
        "random_negative_control": 0.67,
        "title_only_control": 0.65,
    }
    return {
        "schema_version": "1.0.0",
        "artifact_type": "portfolio_ablation_evidence",
        "source_trial_selection_sha256": DIGEST_C,
        "selection_id": TRIAL_ID,
        "git_sha": MODEL_SOURCE_SHA,
        "dataset_manifest_sha256": DIGEST_A,
        "metric": "graded_ndcg@10",
        "test_access_count": 0,
        "selected_model_id": CANDIDATE_MODEL,
        "selected_config_sha256": DIGEST_D,
        "trials": [
            {
                "role": "candidate_treatment",
                "promotion_eligible": True,
                "model_id": CANDIDATE_MODEL,
                "config_id": "candidate-v1",
                "config_sha256": DIGEST_D,
                "input_template_version": "enriched_v1",
                "sampling_strategy": "mixed_hard_random_v1",
                "hard_example_sources": ["bm25", "pretrained_cross_encoder"],
                "validation_graded_ndcg_at_10": treatment_value,
            },
            {
                "role": "random_negative_control",
                "promotion_eligible": False,
                "model_id": "candidate-random-ablation-v1",
                "config_id": "candidate-random-ablation-v1",
                "config_sha256": DIGEST_A,
                "input_template_version": "enriched_v1",
                "sampling_strategy": "random_only_v1",
                "hard_example_sources": [],
                "validation_graded_ndcg_at_10": controls["random_negative_control"],
            },
            {
                "role": "title_only_control",
                "promotion_eligible": False,
                "model_id": "candidate-title-ablation-v1",
                "config_id": "candidate-title-ablation-v1",
                "config_sha256": DIGEST_B,
                "input_template_version": "title_v1",
                "sampling_strategy": "mixed_hard_random_v1",
                "hard_example_sources": ["bm25", "pretrained_cross_encoder"],
                "validation_graded_ndcg_at_10": controls["title_only_control"],
            },
        ],
        "contrasts": [
            {
                "contrast_id": "mixed_vs_random_sampling",
                "control_role": "random_negative_control",
                "controlled_difference_fields": [
                    "config_hash",
                    "config_id",
                    "hard_example_sources",
                    "sampling_strategy",
                ],
                "treatment_validation_graded_ndcg_at_10": treatment_value,
                "control_validation_graded_ndcg_at_10": controls["random_negative_control"],
                "treatment_minus_control": (treatment_value - controls["random_negative_control"]),
            },
            {
                "contrast_id": "enriched_vs_title_input",
                "control_role": "title_only_control",
                "controlled_difference_fields": [
                    "config_hash",
                    "config_id",
                    "input_template_version",
                ],
                "treatment_validation_graded_ndcg_at_10": treatment_value,
                "control_validation_graded_ndcg_at_10": controls["title_only_control"],
                "treatment_minus_control": treatment_value - controls["title_only_control"],
            },
        ],
    }


def _public_evidence(report: dict[str, Any]) -> dict[str, Any]:
    primary = report["primary_metric"]
    paired = report["paired_differences"][0]
    gate = report["release_gate_results"]
    models = [
        {
            "model_id": BASELINE_MODEL,
            "display_name": "Strongest unchanged baseline",
            "kind": "pretrained",
            "graded_ndcg_at_10": primary["strongest_baseline_value"],
            "exact_mrr_at_10": None,
            "recall_exact_or_substitute_at_10": None,
            "pairwise_ordinal_accuracy": None,
            "graded_ndcg_at_5": None,
            "exact_top_1_rate": None,
            "p95_inference_latency_ms": None,
        },
        {
            "model_id": CANDIDATE_MODEL,
            "display_name": "Fine-tuned candidate",
            "kind": "fine_tuned",
            "graded_ndcg_at_10": primary["candidate_value"],
            "exact_mrr_at_10": None,
            "recall_exact_or_substitute_at_10": None,
            "pairwise_ordinal_accuracy": None,
            "graded_ndcg_at_5": None,
            "exact_top_1_rate": None,
            "p95_inference_latency_ms": None,
        },
    ]
    return {
        "schema_version": "1.0.0",
        "evidence_mode": "verified",
        "run": {
            "evidence_mode": "verified",
            "run_id": report["run_id"],
            "status": "complete",
            "config_hash": DIGEST_D,
            "dataset_manifest_hash": DIGEST_A,
            "split_manifest_hash": DIGEST_C,
            "git_sha": SOURCE_SHA,
            "model_artifact_checksum": DIGEST_B,
            "dataset_name": "tiny-esci",
            "dataset_version": "fixture-v1",
            "locale": "us",
            "base_model_id": "cross-encoder-fixture",
            "base_model_revision": "fixture-revision-1",
            "training_strategy": "mixed_hard_random_v1",
            "training_provenance": {
                "trial_selection_id": TRIAL_ID,
                "trial_selection_sha256": DIGEST_C,
                "run_id": "training-run-1",
                "run_manifest_sha256": DIGEST_A,
                "selected_model_id": CANDIDATE_MODEL,
                "selected_model_artifact_checksum": DIGEST_B,
                "config_hash": DIGEST_D,
                "git_sha": MODEL_SOURCE_SHA,
                "image_digest": DIGEST_C,
                "hardware_class": "ml.g4dn.xlarge",
                "accelerator": "gpu",
                "region": "us-east-1",
                "runtime_seconds": 60.0,
                "estimated_cost_usd": 0.8,
                "actual_cost_usd": None,
                "cost_evidence": "Fixture training estimate; final charge is not reconciled.",
            },
            "evaluation_provenance": {
                "candidate_model_id": CANDIDATE_MODEL,
                "candidate_model_artifact_checksum": DIGEST_B,
                "evaluation_config_hash": DIGEST_A,
                "git_sha": SOURCE_SHA,
                "image_digest": DIGEST_B,
                "hardware_class": "ml.m5.xlarge",
                "region": "us-east-1",
                "clean_execution_count": 2,
                "runtime_seconds": 60.0,
                "runtime_basis": "processing_job_wall_clock_sum",
                "estimated_cost_usd": 0.25,
                "actual_cost_usd": None,
                "cost_evidence": "Fixture evaluation estimate; final charge is not reconciled.",
            },
            "metrics": {
                "candidate_graded_ndcg_at_10": primary["candidate_value"],
                "strongest_baseline_graded_ndcg_at_10": primary["strongest_baseline_value"],
                "candidate_minus_baseline_graded_ndcg_at_10": primary["candidate_minus_baseline"],
            },
            "intervals": {
                "candidate_minus_baseline_graded_ndcg_at_10": {
                    "point_estimate": paired["point_estimate"],
                    "lower": paired["ci_lower"],
                    "upper": paired["ci_upper"],
                    "confidence_level": paired["confidence_level"],
                }
            },
            "test_access_count": report["test_access_count"],
            "limitations": report["limitations"],
            "prohibited_claims": [
                "No claim of shopper, conversion, revenue, or production-scale impact."
            ],
            "reproduction_command": "gh workflow run release.yml --ref " + SOURCE_SHA,
        },
        "evaluation": {
            "evidence_mode": "verified",
            "report_id": report["report_id"],
            "run_id": report["run_id"],
            "candidate_model_id": CANDIDATE_MODEL,
            "strongest_baseline_model_id": BASELINE_MODEL,
            "release_status": "passed" if gate["passed"] else "failed",
            "primary_metric": {
                "metric": "graded_ndcg@10",
                "display_name": "Graded nDCG@10",
                "value": primary["candidate_value"],
                "interval": None,
            },
            "strongest_baseline": {
                "metric": "graded_ndcg@10",
                "display_name": "Strongest unchanged baseline",
                "value": primary["strongest_baseline_value"],
                "interval": None,
            },
            "delta": {
                "metric": "graded_ndcg@10",
                "display_name": "Candidate minus baseline",
                "value": primary["candidate_minus_baseline"],
                "interval": {
                    "point_estimate": paired["point_estimate"],
                    "lower": paired["ci_lower"],
                    "upper": paired["ci_upper"],
                    "confidence_level": paired["confidence_level"],
                },
            },
            "held_out_query_count": report["query_count"],
            "bootstrap_resamples": report["bootstrap_resamples"],
            "bootstrap_seed": report["bootstrap_seed"],
            "test_access_count": report["test_access_count"],
            "excluded_query_count": report["excluded_query_count"],
            "exclusion_note": "Fixture held-out exclusion policy.",
            "models": models,
            "secondary_metrics": [],
        },
        "failure_analysis": {
            "evidence_mode": "verified",
            "run_id": report["run_id"],
            "metric": "graded_ndcg@10",
            "minimum_slice_size": 50,
            "slices": [],
            "examples": [
                {
                    "example_id": f"{item['category']}:{item['query_id']}",
                    "query": {
                        "query_id": item["query_id"],
                        "query": f"Public fixture query {index}",
                        "candidate_count": 40,
                    },
                    "category": item["category"],
                    "baseline_metric": item["baseline_metric"],
                    "candidate_metric": item["candidate_metric"],
                    "delta": item["delta"],
                    "selection_rule": item["selection_rule"],
                    "public_product_ids": item.get("public_product_ids", []),
                    "notes": item.get("notes"),
                    "interpretation": None,
                    "next_experiment": None,
                }
                for index, item in enumerate(report["example_results"], start=1)
            ],
        },
    }


def _baseline_pointer() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "release_id": BASELINE_RELEASE,
        "model_id": BASELINE_MODEL,
        "bundle_s3_key": f"promoted/{BASELINE_MODEL}/",
        "evaluation_report_id": "validation-report",
        "git_sha": BASELINE_SHA,
        "evidence_mode": "validation_only",
        "release_decision": "validation_baseline",
        "gate_passed": None,
        "evaluated_candidate_model_id": None,
        "previous": None,
    }


def _release_pointer(gate_passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "release_id": VERIFIED_RELEASE,
        "model_id": CANDIDATE_MODEL if gate_passed else BASELINE_MODEL,
        "bundle_s3_key": f"promoted/releases/{VERIFIED_RELEASE}/",
        "evaluation_report_id": VERIFIED_RELEASE,
        "git_sha": SOURCE_SHA,
        "evidence_mode": "verified",
        "release_decision": "promote_candidate" if gate_passed else "retain_baseline",
        "gate_passed": gate_passed,
        "evaluated_candidate_model_id": CANDIDATE_MODEL,
        "previous": {
            "release_id": BASELINE_RELEASE,
            "model_id": BASELINE_MODEL,
            "pointer_version_id": "pointer-baseline-v1",
        },
    }


def _cold_start(
    release_id: str,
    model_id: str,
    production_version: str,
    previous_version: str,
) -> dict[str, Any]:
    cold = deepcopy(valid_cold_start())
    cold["measured_at"] = "2026-09-02T11:59:00Z"
    cold["identifiers"].update(
        {
            "release_id": release_id,
            "model_id": model_id,
            "dataset_manifest_hash": DIGEST_A,
            "model_artifact_checksum": DIGEST_B,
            "function_version": production_version,
        }
    )
    cold["control_proof"]["previous_candidate_version"] = previous_version
    return cold


def _deployment_evidence(
    release_id: str,
    model_id: str,
    previous_version: str,
    production_version: str,
    pointer_version: str,
    image_digest: str,
) -> dict[str, Any]:
    smoke = deepcopy(valid_smoke())
    smoke.update(
        {
            "base_url_origin": ORIGIN,
            "model_id": model_id,
            "evaluated_candidate_model_id": CANDIDATE_MODEL,
        }
    )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "deployment_evidence",
        "release_id": release_id,
        "model_id": model_id,
        "code_commit": DEPLOYMENT_SHA,
        "serving_image_digest": image_digest,
        "previous_lambda_version": previous_version,
        "production_lambda_version": production_version,
        "promoted_pointer_version_id": pointer_version,
        "smoke_tests_passed": True,
        "controlled_cold_start": _cold_start(
            release_id, model_id, production_version, previous_version
        ),
        "candidate_api_gate": valid_candidate_gate(),
        "production_api_smoke": smoke,
        "browser_smoke": {"desktop": True, "mobile": True, "keyboard": True},
    }


def _deployment_handoff(
    stage: str,
    run_id: int,
    evidence: dict[str, Any],
    previous_pointer: dict[str, Any],
) -> dict[str, Any]:
    cold = evidence["controlled_cold_start"]
    gate = evidence["candidate_api_gate"]
    return {
        **_base(stage, DEPLOYMENT_SHA, run_id),
        "release_id": evidence["release_id"],
        "model_id": evidence["model_id"],
        "serving_image_digest": evidence["serving_image_digest"],
        "previous_lambda_version": evidence["previous_lambda_version"],
        "production_lambda_version": evidence["production_lambda_version"],
        "promoted_pointer_version_id": evidence["promoted_pointer_version_id"],
        "previous_release_id": previous_pointer["release_id"],
        "previous_model_id": previous_pointer["model_id"],
        "public_origin": ORIGIN,
        "controlled_cold_start_ms": cold["first_request"]["end_to_end_latency_ms"],
        "candidate_gate_error_rate": gate["error_rate"],
        "candidate_gate_p95_ms": gate["end_to_end_latency_ms"]["p95"],
    }


def _write_deployment_stage(
    root: Path,
    stage: str,
    run_id: int,
    evidence: dict[str, Any],
    pointer: dict[str, Any],
    previous_pointer: dict[str, Any],
) -> Path:
    stage_root = _stage(
        root,
        DEPLOYMENT_SHA,
        stage,
        _deployment_handoff(stage, run_id, evidence, previous_pointer),
    )
    _write(stage_root / "deployment-evidence.json", evidence)
    _write(stage_root / "promotion-pointer.json", pointer)
    _write(stage_root / "previous-promotion-pointer.json", previous_pointer)
    _write(stage_root / "active-promotion-pointer.json", pointer)
    return stage_root


def _lambda_configuration(model_id: str) -> dict[str, Any]:
    configuration: dict[str, Any] = deepcopy(valid_performance_report()["lambda_configuration"])
    configuration.update(
        {
            "benchmark_run_id": BENCHMARK_RUN_ID,
            "release_id": VERIFIED_RELEASE,
            "model_id": model_id,
            "function_version": "11",
        }
    )
    return configuration


def _performance_report(
    model_id: str,
    pointer: dict[str, Any],
    deployment: dict[str, Any],
    deployment_sha256: str,
    public_evidence_sha256: str,
) -> dict[str, Any]:
    report = deepcopy(valid_performance_report())
    report["identifiers"].update(
        {
            "benchmark_run_id": BENCHMARK_RUN_ID,
            "release_id": VERIFIED_RELEASE,
            "public_run_id": "public-run-1",
            "model_id": model_id,
            "release_git_sha": SOURCE_SHA,
            "benchmark_harness_git_sha": DEPLOYMENT_SHA,
            "dataset_manifest_hash": DIGEST_A,
            "model_artifact_checksum": DIGEST_B,
            "public_origin": ORIGIN,
        }
    )
    report["release_binding"].update(
        {
            "promotion_pointer_version_id": "pointer-winner-v1",
            "bundle_s3_key": pointer["bundle_s3_key"],
            "deployment_evidence_sha256": deployment_sha256,
            "public_evidence_sha256": public_evidence_sha256,
        }
    )
    report["lambda_configuration"] = _lambda_configuration(model_id)
    report["controlled_cold_start"] = deployment["controlled_cold_start"]
    return report


def _cost_preflight(model_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "benchmark_cost_preflight",
        "status": "passed",
        "checked_at": "2026-09-02T12:00:00Z",
        "benchmark_run_id": BENCHMARK_RUN_ID,
        "release_id": VERIFIED_RELEASE,
        "model_id": model_id,
        "region": "us-east-1",
        "public_origin": ORIGIN,
        "maximum_out_of_pocket_usd": "0",
        "campaign_envelope_usd": "40",
        "required_credit_reserve_usd": "40",
        "conservative_benchmark_allowance_usd": "0.50",
        "heldout_access_enabled": False,
        "sensitive_balance_values_recorded": False,
        "financial_snapshot": deepcopy(FINANCIAL_SNAPSHOT),
    }


def _write_benchmark_stage(
    root: Path,
    winner_pointer: dict[str, Any],
    winner_evidence: dict[str, Any],
    winner_root: Path,
) -> None:
    model_id = winner_pointer["model_id"]
    report = _performance_report(
        model_id,
        winner_pointer,
        winner_evidence,
        _digest(winner_root / "deployment-evidence.json"),
        "sha256:"
        + hashlib.sha256(
            (
                json.dumps(_read(winner_root / "candidate-run.json"), indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8")
        ).hexdigest(),
    )
    benchmark_root = root / DEPLOYMENT_SHA / "benchmark"
    _write(benchmark_root / "controlled-cold-start.json", winner_evidence["controlled_cold_start"])
    _write(benchmark_root / "cost-preflight.json", _cost_preflight(model_id))
    _write(benchmark_root / "lambda-configuration.json", _lambda_configuration(model_id))
    _write(benchmark_root / "performance-report.json", report)
    _write(
        benchmark_root / "validation.json",
        {
            "schema_version": "1.0.0",
            "status": "passed",
            "validated_at": "2026-09-02T12:10:01Z",
            "benchmark_run_id": BENCHMARK_RUN_ID,
            "release_id": VERIFIED_RELEASE,
            "model_id": model_id,
            "performance_report_sha256": _digest(benchmark_root / "performance-report.json"),
            "evidence_file_count": 5,
            "condition_count": 9,
            "controlled_cold_start_sample_count": 1,
            "warmup_request_count": 90,
            "measured_request_count": 1800,
            "success_thresholds_enforced": True,
            "minimum_warmup_condition_success_count": 10,
            "primary_latency_condition_success_count": 200,
            "minimum_secondary_condition_success_count": 200,
            "immutability_required": True,
        },
    )
    durable_names = (
        "controlled-cold-start.json",
        "cost-preflight.json",
        "lambda-configuration.json",
        "performance-report.json",
        "validation.json",
    )
    _write(
        benchmark_root / "evidence-checksums.json",
        {
            "schema_version": "1.0.0",
            "files": {name: _digest(benchmark_root / name) for name in durable_names},
        },
    )
    checksum_sha = _digest(benchmark_root / "evidence-checksums.json")
    prefix = (
        f"public/{VERIFIED_RELEASE}/performance/runs/{BENCHMARK_RUN_ID}/"
        f"sha256-{checksum_sha.removeprefix('sha256:')}/"
    )
    (benchmark_root / "published-prefix.txt").write_text(prefix + "\n", encoding="utf-8")
    primary = next(
        condition
        for condition in report["conditions"]
        if condition["candidate_count"] == 40 and condition["offered_concurrency"] == 1
    )
    totals = report["totals"]
    cold = winner_evidence["controlled_cold_start"]
    _write(
        benchmark_root / "_handoff.json",
        {
            **_base("benchmark", DEPLOYMENT_SHA, 2002),
            "benchmark_run_id": BENCHMARK_RUN_ID,
            "release_id": VERIFIED_RELEASE,
            "model_id": model_id,
            "public_origin": ORIGIN,
            "published_prefix": prefix,
            "measured_request_count": totals["measured_request_count"],
            "measured_success_count": totals["measured_success_count"],
            "measured_error_count": totals["measured_error_count"],
            "measured_throttle_count": totals["measured_throttle_count"],
            "primary_end_to_end_latency_ms": primary["measured"]["end_to_end_latency_ms"],
            "primary_model_latency_ms": primary["measured"]["model_latency_ms"],
            "primary_serialization_latency_ms": primary["measured"]["serialization_latency_ms"],
            "controlled_cold_start_ms": cold["first_request"]["end_to_end_latency_ms"],
            "controlled_cold_init_ms": cold["lambda_report"]["init_duration_ms"],
            "controlled_cold_max_memory_mb": cold["lambda_report"]["max_memory_used_mb"],
        },
    )


def _fixture(root: Path, *, gate_passed: bool = True) -> None:
    root.mkdir()
    report = _evaluation_report(gate_passed)
    provenance = _evaluation_provenance(report)
    summary = _release_summary(report)
    baseline_pointer = _baseline_pointer()
    winner_pointer = _release_pointer(gate_passed)
    release_root = _stage(
        root,
        SOURCE_SHA,
        "release",
        {
            **_base("release", SOURCE_SHA, 1001),
            "release_id": VERIFIED_RELEASE,
            "model_id": winner_pointer["model_id"],
            "bundle_s3_key": winner_pointer["bundle_s3_key"],
            "evaluation_report_id": VERIFIED_RELEASE,
            "release_decision": report["release_gate_results"]["decision"],
            "gate_passed": gate_passed,
            "evaluated_candidate_model_id": CANDIDATE_MODEL,
            "previous_release_id": BASELINE_RELEASE,
            "previous_model_id": BASELINE_MODEL,
            "previous_pointer_version_id": "pointer-baseline-v1",
            "candidate_metric": report["primary_metric"]["candidate_value"],
            "strongest_baseline_id": BASELINE_MODEL,
            "strongest_baseline_metric": 0.68,
            "candidate_minus_baseline": report["primary_metric"]["candidate_minus_baseline"],
            "paired_differences": report["paired_differences"],
            "release_gate_reasons": report["release_gate_results"]["reasons"],
            "evaluation_image_digest": DIGEST_B,
            "trial_selection_id": TRIAL_ID,
            "trial_selection_sha256": DIGEST_C,
        },
    )
    _write(release_root / "evaluation-report.json", report)
    _write(release_root / "evaluation-provenance.json", provenance)
    _write(release_root / "release-summary.json", summary)
    _write(release_root / "portfolio-ablation-evidence.json", _portfolio_ablations())
    _write(release_root / "previous-pointer.json", baseline_pointer)
    _write(release_root / "promotion-pointer.json", winner_pointer)

    baseline_evidence = _deployment_evidence(
        BASELINE_RELEASE,
        BASELINE_MODEL,
        "1",
        "10",
        "pointer-baseline-v1",
        DIGEST_D,
    )
    _write_deployment_stage(
        root,
        "deploy-baseline",
        2000,
        baseline_evidence,
        baseline_pointer,
        baseline_pointer,
    )
    winner_model = winner_pointer["model_id"]
    winner_evidence = _deployment_evidence(
        VERIFIED_RELEASE,
        winner_model,
        "10",
        "11",
        "pointer-winner-v1",
        DIGEST_C,
    )
    winner_root = _write_deployment_stage(
        root,
        "deploy-winner",
        2001,
        winner_evidence,
        winner_pointer,
        baseline_pointer,
    )
    _write(winner_root / "candidate-run.json", _public_evidence(report))
    _write_benchmark_stage(root, winner_pointer, winner_evidence, winner_root)

    rollback_root = _stage(
        root,
        DEPLOYMENT_SHA,
        "rollback",
        {
            **_base("rollback", DEPLOYMENT_SHA, 2003),
            "restored_release_id": BASELINE_RELEASE,
            "restored_model_id": BASELINE_MODEL,
            "from_lambda_version": "11",
            "to_lambda_version": "10",
            "restored_pointer_version_id": "pointer-baseline-v1",
        },
    )
    _write(
        rollback_root / "rollback-evidence.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "manual_rollback_evidence",
            "restored_release_id": BASELINE_RELEASE,
            "restored_model_id": BASELINE_MODEL,
            "from_lambda_version": "11",
            "to_lambda_version": "10",
            "restored_pointer_version_id": "pointer-baseline-v1",
            "workflow_commit": DEPLOYMENT_SHA,
            "smoke_test_passed": True,
        },
    )
    redeploy_evidence = _deployment_evidence(
        VERIFIED_RELEASE,
        winner_model,
        "10",
        "12",
        "pointer-winner-v2",
        DIGEST_C,
    )
    _write_deployment_stage(
        root,
        "redeploy-winner",
        2004,
        redeploy_evidence,
        winner_pointer,
        baseline_pointer,
    )


def _assemble(root: Path) -> dict[str, Any]:
    return assembler.assemble(
        root,
        MODEL_SOURCE_SHA,
        SOURCE_SHA,
        DEPLOYMENT_SHA,
        generated_at="2026-09-18T09:00:00Z",
        public_demo_expires_at="2026-09-19T08:00:00Z",
    )


def test_assembler_binds_typed_chain_and_derives_serialization(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)

    payload = _assemble(root)

    assert payload["release_gate"]["passed"] is True
    assert payload["identities"]["model_source_git_sha"] == MODEL_SOURCE_SHA
    assert payload["identities"]["release_git_sha"] == SOURCE_SHA
    assert "workflow_run_ids" not in payload
    assert payload["rollback"]["verified"] is True
    assert payload["redeployment"]["exact_winner_redeployed"] is True
    assert payload["redeployment"]["fresh_runtime_revision_published"] is True
    assert payload["benchmark"]["primary_serialization_latency_ms"]["p95"] == pytest.approx(47.5125)
    rendered = json.dumps(payload, sort_keys=True)
    for marker in (
        "product-search-ranking-prod",
        "pointer-winner-v1",
        "deployment-version",
        "etag-",
        "published_prefix",
        '"1001"',
        '"2000"',
        '"2001"',
        '"2002"',
        '"2003"',
        '"2004"',
        "heldout-run",
        "training-run-1",
    ):
        assert marker not in rendered
    target = assembler.write_immutable(payload, tmp_path / "committed-releases")
    assert target.name == f"{VERIFIED_RELEASE}.json"


def test_portfolio_release_schema_matches_the_strict_pydantic_contract() -> None:
    document = json.loads(
        Path("schemas/json/portfolio_release_evidence.schema.json").read_text(encoding="utf-8")
    )
    assert document.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert document.pop("$id").endswith("/portfolio_release_evidence.schema.json")
    assert document == assembler.PortfolioReleaseEvidence.model_json_schema()


def test_assembler_rejects_tampered_sanitized_ablation_values(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / SOURCE_SHA / "release" / "portfolio-ablation-evidence.json"
    evidence = _read(path)
    evidence["contrasts"][0]["treatment_minus_control"] = 0.9
    _write(path, evidence)

    with pytest.raises(assembler.ReleaseEvidenceError, match="typed contract"):
        _assemble(root)


def test_assembler_rejects_unsupported_served_public_fields(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / DEPLOYMENT_SHA / "deploy-winner" / "candidate-run.json"
    evidence = _read(path)
    evidence["run"]["private_workflow_run_id"] = "123456789"
    _write(path, evidence)

    with pytest.raises(assembler.ReleaseEvidenceError, match="typed contract"):
        _assemble(root)


def test_assembler_checksum_binds_the_served_public_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / DEPLOYMENT_SHA / "deploy-winner" / "candidate-run.json"
    evidence = _read(path)
    evidence["failure_analysis"]["examples"][0]["query"]["query"] = "Tampered query text"
    _write(path, evidence)

    with pytest.raises(assembler.ReleaseEvidenceError, match="bundle checksum"):
        _assemble(root)


def test_assembler_preserves_a_contract_valid_negative_result(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root, gate_passed=False)

    payload = _assemble(root)

    assert payload["release_gate"] == {
        "passed": False,
        "decision": "retain_baseline",
        "promoted_model_id": BASELINE_MODEL,
        "evaluated_candidate_model_id": CANDIDATE_MODEL,
        "strongest_baseline_model_id": BASELINE_MODEL,
    }
    assert payload["metrics"]["candidate_minus_baseline"] < 0


def test_assembler_rejects_unknown_handoff_fields(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / SOURCE_SHA / "release" / "_handoff.json"
    handoff = _read(path)
    handoff["unexpected_private_receipt"] = "must-not-pass"
    _write(path, handoff)

    with pytest.raises(assembler.ReleaseEvidenceError, match="exact expected fields"):
        _assemble(root)


def test_assembler_rejects_a_tampered_benchmark_artifact(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / DEPLOYMENT_SHA / "benchmark" / "performance-report.json"
    report = _read(path)
    report["limitations"].append("tampered after checksumming")
    _write(path, report)

    with pytest.raises(assembler.ReleaseEvidenceError, match="artifact checksum differs"):
        _assemble(root)


def test_assembler_rejects_mutable_serialization_sidecar_claim(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / DEPLOYMENT_SHA / "benchmark" / "_handoff.json"
    handoff = _read(path)
    handoff["primary_serialization_latency_ms"]["p95"] = 0.01
    _write(path, handoff)

    with pytest.raises(assembler.ReleaseEvidenceError, match=r"benchmark handoff .* differs"):
        _assemble(root)


def test_assembler_rejects_mutable_release_sidecar_claim(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / SOURCE_SHA / "release" / "_handoff.json"
    handoff = _read(path)
    handoff["candidate_metric"] = 0.99
    _write(path, handoff)

    with pytest.raises(
        assembler.ReleaseEvidenceError, match="release handoff candidate_metric differs"
    ):
        _assemble(root)


def test_assembler_requires_the_exact_baseline_stage(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    (root / DEPLOYMENT_SHA / "deploy-baseline" / "_handoff.json").unlink()

    with pytest.raises(assembler.ReleaseEvidenceError, match="required evidence is absent"):
        _assemble(root)


def test_assembler_rejects_redeploying_different_pointer_bytes(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    stage_root = root / DEPLOYMENT_SHA / "redeploy-winner"
    path = stage_root / "promotion-pointer.json"
    pointer = _read(path)
    pointer["evaluation_report_id"] = "different-report"
    _write(path, pointer)
    _write(stage_root / "active-promotion-pointer.json", pointer)

    with pytest.raises(assembler.ReleaseEvidenceError, match="pointer bytes differ"):
        _assemble(root)


def test_assembler_requires_a_fresh_redeployment_runtime_version(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    stage_root = root / DEPLOYMENT_SHA / "redeploy-winner"
    evidence_path = stage_root / "deployment-evidence.json"
    evidence = _read(evidence_path)
    evidence["production_lambda_version"] = "11"
    evidence["controlled_cold_start"]["identifiers"]["function_version"] = "11"
    _write(evidence_path, evidence)
    handoff_path = stage_root / "_handoff.json"
    handoff = _read(handoff_path)
    handoff["production_lambda_version"] = "11"
    _write(handoff_path, handoff)

    with pytest.raises(assembler.ReleaseEvidenceError, match="fresh Lambda version"):
        _assemble(root)


@pytest.mark.parametrize("stage", ("deploy-baseline", "deploy-winner", "redeploy-winner"))
def test_assembler_requires_every_deployment_to_publish_a_new_runtime_version(
    tmp_path: Path, stage: str
) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    stage_root = root / DEPLOYMENT_SHA / stage
    evidence_path = stage_root / "deployment-evidence.json"
    evidence = _read(evidence_path)
    evidence["production_lambda_version"] = evidence["previous_lambda_version"]
    evidence["controlled_cold_start"]["identifiers"]["function_version"] = evidence[
        "previous_lambda_version"
    ]
    evidence["controlled_cold_start"]["control_proof"]["previous_candidate_version"] = "999"
    _write(evidence_path, evidence)
    handoff_path = stage_root / "_handoff.json"
    handoff = _read(handoff_path)
    handoff["production_lambda_version"] = handoff["previous_lambda_version"]
    _write(handoff_path, handoff)

    with pytest.raises(
        assembler.ReleaseEvidenceError, match="did not publish a new Lambda version"
    ):
        _assemble(root)


def test_assembler_requires_rollback_to_change_the_runtime_version(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    stage_root = root / DEPLOYMENT_SHA / "rollback"
    evidence_path = stage_root / "rollback-evidence.json"
    evidence = _read(evidence_path)
    evidence["from_lambda_version"] = evidence["to_lambda_version"]
    _write(evidence_path, evidence)
    handoff_path = stage_root / "_handoff.json"
    handoff = _read(handoff_path)
    handoff["from_lambda_version"] = handoff["to_lambda_version"]
    _write(handoff_path, handoff)

    with pytest.raises(assembler.ReleaseEvidenceError, match="rollback did not change"):
        _assemble(root)


def test_positive_gate_requires_the_deployed_baseline_to_be_the_strongest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    release_root = root / SOURCE_SHA / "release"
    previous_path = release_root / "previous-pointer.json"
    previous = _read(previous_path)
    previous["model_id"] = "different-baseline"
    previous["bundle_s3_key"] = "promoted/different-baseline/"
    _write(previous_path, previous)
    pointer_path = release_root / "promotion-pointer.json"
    pointer = _read(pointer_path)
    pointer["previous"]["model_id"] = "different-baseline"
    _write(pointer_path, pointer)
    handoff_path = release_root / "_handoff.json"
    handoff = _read(handoff_path)
    handoff["previous_model_id"] = "different-baseline"
    _write(handoff_path, handoff)

    with pytest.raises(assembler.ReleaseEvidenceError, match="evaluated strongest baseline"):
        _assemble(root)


def test_assembler_requires_active_promotion_pointer_proof(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    (root / DEPLOYMENT_SHA / "deploy-winner" / "active-promotion-pointer.json").unlink()

    with pytest.raises(assembler.ReleaseEvidenceError, match="required evidence is absent"):
        _assemble(root)


def test_assembler_rejects_tampered_active_promotion_pointer_proof(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / DEPLOYMENT_SHA / "deploy-winner" / "active-promotion-pointer.json"
    pointer = _read(path)
    pointer["evaluation_report_id"] = "different-report"
    _write(path, pointer)

    with pytest.raises(assembler.ReleaseEvidenceError, match="active promotion pointer differs"):
        _assemble(root)


def test_assembler_cross_binds_clean_evaluation_receipts(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    path = root / SOURCE_SHA / "release" / "release-summary.json"
    summary = _read(path)
    summary["test_access_count"] = 1
    _write(path, summary)

    with pytest.raises(assembler.ReleaseEvidenceError, match="clean-evaluation binding differs"):
        _assemble(root)


def test_assembler_binds_summary_to_the_evaluation_config_checksum(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    release_root = root / SOURCE_SHA / "release"
    provenance = _read(release_root / "evaluation-provenance.json")
    summary_path = release_root / "release-summary.json"
    summary = _read(summary_path)
    assert summary["evaluation_config_hash"] == provenance["evaluation_config_checksum"]
    assert summary["evaluation_config_hash"] != provenance["config_hash"]
    _assemble(root)

    summary["evaluation_config_hash"] = DIGEST_C
    _write(summary_path, summary)
    with pytest.raises(assembler.ReleaseEvidenceError, match="clean-evaluation binding differs"):
        _assemble(root)


def test_public_filter_rejects_private_text_in_allowlisted_values(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    payload = _assemble(root)
    payload["claim_boundaries"]["limitations"][0] = "person@example.com"
    payload["public_evidence"]["limitations"][0] = "person@example.com"
    with pytest.raises(assembler.ReleaseEvidenceError, match="private text"):
        assembler.write_immutable(payload, tmp_path / "committed-releases")


def test_public_filter_rejects_numeric_github_workflow_ids(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    payload = _assemble(root)
    payload["workflow_run_ids"] = {"release": "123456789"}
    with pytest.raises(assembler.ReleaseEvidenceError, match="violates its contract"):
        assembler.write_immutable(payload, tmp_path / "committed-releases")


def test_immutable_writer_refuses_different_replacement(tmp_path: Path) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    payload = _assemble(root)
    output = tmp_path / "committed-releases"
    assembler.write_immutable(payload, output)

    with pytest.raises(assembler.ReleaseEvidenceError, match="already differs"):
        assembler.write_immutable({**payload, "generated_at": "2026-09-18T09:00:01Z"}, output)


def test_immutable_writer_never_clobbers_a_concurrent_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "local-evidence"
    _fixture(root)
    first = _assemble(root)
    second = deepcopy(first)
    second["generated_at"] = "2026-09-18T09:00:01Z"
    output = tmp_path / "committed-releases"
    output.mkdir()
    barrier = Barrier(2)
    real_link = os.link

    def synchronized_link(source: Path, target: Path) -> None:
        barrier.wait(timeout=5)
        real_link(source, target)

    monkeypatch.setattr(os, "link", synchronized_link)

    def attempt(payload: dict[str, Any]) -> tuple[str, str]:
        try:
            return "ok", assembler.write_immutable(payload, output).read_text(encoding="utf-8")
        except assembler.ReleaseEvidenceError as error:
            return "error", str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (first, second)))

    assert sorted(status for status, _ in results) == ["error", "ok"]
    expected = {
        json.dumps(
            assembler.PortfolioReleaseEvidence.model_validate(payload).model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
        for payload in (first, second)
    }
    assert (output / f"{VERIFIED_RELEASE}.json").read_text(encoding="utf-8") in expected
