from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.cold_start_evidence import build_evidence
from search_rank.schemas.performance import ColdStartEvidence

VERSION = "7"
MODEL_ID = "candidate-v1"
DATASET_HASH = "sha256:" + "a" * 64
MODEL_CHECKSUM = "sha256:" + "b" * 64
REQUEST_ID = "cold-123-1-v7"
STREAM = "2026/09/02/[7]abcdef123456"


def _structured(**values: Any) -> str:
    return json.dumps(values, sort_keys=True)


def _valid_inputs() -> dict[str, Any]:
    return {
        "function_metadata": {
            "Configuration": {
                "FunctionName": "product-search-api",
                "Version": VERSION,
                "LastModified": "2026-09-02T20:00:01.000+0000",
                "MemorySize": 4096,
                "Architectures": ["x86_64"],
            },
            "Concurrency": {"ReservedConcurrentExecutions": 2},
        },
        "prior_events": {"events": []},
        "observed_events": {
            "events": [
                {
                    "logStreamName": STREAM,
                    "message": _structured(
                        message="service_startup_success",
                        startup_success=True,
                        model_load_duration_ms=822.5,
                        model_id=MODEL_ID,
                        error_code=None,
                    ),
                },
                {
                    "logStreamName": STREAM,
                    "message": _structured(
                        message="api_request",
                        request_id=REQUEST_ID,
                        route="/api/v1/rank",
                        model_id=MODEL_ID,
                        query_id="q40",
                        candidate_count=40,
                        memory_used_mb=812.25,
                        status_code=200,
                        error_code=None,
                    ),
                },
                {
                    "logStreamName": STREAM,
                    "message": (
                        "REPORT RequestId: 11111111-1111-1111-1111-111111111111\t"
                        "Duration: 1200.50 ms\tBilled Duration: 1800 ms\t"
                        "Memory Size: 4096 MB\tMax Memory Used: 1024 MB\t"
                        "Init Duration: 599.25 ms"
                    ),
                },
            ]
        },
        "response": {
            "query_id": "q40",
            "model_id": MODEL_ID,
            "dataset_manifest_hash": DATASET_HASH,
            "model_artifact_checksum": MODEL_CHECKSUM,
            "candidate_count": 40,
            "top_k": 40,
            "latency_ms": 321.5,
            "results": [{"product_id": str(index)} for index in range(40)],
        },
        "function_name": "product-search-api",
        "alias": "candidate",
        "version": VERSION,
        "previous_version": "6",
        "release_id": "release-1",
        "expected_model_id": MODEL_ID,
        "expected_dataset_hash": DATASET_HASH,
        "expected_model_checksum": MODEL_CHECKSUM,
        "request_id": REQUEST_ID,
        "request_started_at": "2026-09-02T20:00:02+00:00",
        "end_to_end_ms": 2000.25,
        "candidate_count": 40,
        "apply_started_epoch_ms": 1_788_379_200_000,
    }


def test_build_evidence_separates_a_proven_cold_sample_from_warm_samples() -> None:
    evidence = build_evidence(**_valid_inputs())
    validated = ColdStartEvidence.model_validate(evidence)

    assert validated.controlled_cold_start is True
    assert evidence["control_proof"] == {
        "newly_published_after_apply_started": True,
        "candidate_version_changed": True,
        "previous_candidate_version": "6",
        "new_version_prior_cloudwatch_event_count": 0,
        "on_demand_execution": True,
        "reserved_concurrency": 2,
        "provisioned_concurrency": 0,
    }
    assert evidence["first_request"]["end_to_end_latency_ms"] == 2000.25
    assert evidence["lambda_report"]["init_duration_ms"] == 599.25
    assert evidence["structured_startup"]["model_load_duration_ms"] == 822.5
    assert evidence["lambda_report"]["max_memory_used_mb"] == 1024
    assert evidence["structured_request"]["process_peak_memory_mb"] == 812.25
    assert evidence["sample_count"] == 1
    assert evidence["excluded_from_warm_samples"] is True


def test_checked_in_cold_start_schema_matches_the_runtime_contract() -> None:
    document = json.loads(
        Path("schemas/json/cold_start_evidence.schema.json").read_text(encoding="utf-8")
    )
    assert document.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert document.pop("$id").endswith("/cold_start_evidence.schema.json")
    assert document == ColdStartEvidence.model_json_schema()


def test_build_evidence_refuses_a_candidate_version_with_prior_events() -> None:
    inputs = _valid_inputs()
    inputs["prior_events"] = {
        "events": [{"logStreamName": STREAM, "message": "START RequestId: previous"}]
    }

    with pytest.raises(ValueError, match="events before the measured request"):
        build_evidence(**inputs)


def test_build_evidence_refuses_missing_cloudwatch_init_duration() -> None:
    inputs = _valid_inputs()
    inputs["observed_events"]["events"][-1]["message"] = (
        "REPORT RequestId: id\tDuration: 1200 ms\tBilled Duration: 1200 ms\t"
        "Memory Size: 4096 MB\tMax Memory Used: 1024 MB"
    )

    with pytest.raises(ValueError, match="one startup, request, and Lambda REPORT"):
        build_evidence(**inputs)


def test_build_evidence_refuses_a_version_not_published_by_this_apply() -> None:
    inputs = _valid_inputs()
    inputs["apply_started_epoch_ms"] = 1_788_379_205_000

    with pytest.raises(ValueError, match="not newly published"):
        build_evidence(**inputs)


def test_cloud_workflows_keep_controlled_cold_and_warm_measurements_separate() -> None:
    deploy_path = Path(".github/workflows/deploy.yml")
    benchmark_path = Path(".github/workflows/benchmark-serving.yml")
    deploy = deploy_path.read_text(encoding="utf-8")
    benchmark = benchmark_path.read_text(encoding="utf-8")

    assert deploy.index("Measure the newly published candidate's first on-demand invocation") < (
        deploy.index("Run the candidate API contract, error-rate, and primary latency gates")
    )
    assert "candidate version was not newly published by this deployment apply" in deploy
    assert "candidate-cold-prior-events-private.json" in deploy
    assert "--previous-version" in deploy
    assert "--qualifier candidate" in deploy
    assert 'controlled_cold_sample_included": False' in deploy
    assert "--slurpfile controlled_cold_start candidate-cold-start.json" in deploy
    assert '"measurement_class": "warm_after_explicit_per_condition_warmups"' in benchmark
    assert '"controlled_cold_sample_included": False' in benchmark
    assert '"pre_benchmark_observations_included": False' in benchmark
    assert '"controlled_cold_start": controlled_cold_start' in benchmark
    assert "MEASURED_REQUESTS = 200" in benchmark
    assert "WARMUP_REQUESTS = 10" in benchmark

    for path in (deploy_path, benchmark_path):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        scripts = [
            step["run"]
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("run"), str)
        ]
        snippets = [
            snippet.split("\nPY", 1)[0]
            for script in scripts
            for snippet in script.split("python - <<'PY'\n")[1:]
        ]
        assert snippets
        for index, snippet in enumerate(snippets):
            compile(snippet, f"{path.name}-inline-{index}.py", "exec")
