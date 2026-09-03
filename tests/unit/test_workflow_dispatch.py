from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pytest
import yaml

from scripts.validate_workflow_dispatch import WorkflowName, main, validate_dispatch_config

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "workflow-inputs"
WORKFLOWS = ROOT / ".github" / "workflows"

EXTERNAL_ENVIRONMENTS = {
    "train": {
        "ARTIFACT_BUCKET": "example-artifacts-bucket",
        "TRAIN_REPOSITORY": (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/product-search-ranking-train"
        ),
    },
    "release": {
        "ARTIFACT_BUCKET": "example-artifacts-bucket",
        "EVAL_REPOSITORY": (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/product-search-ranking-eval"
        ),
    },
    "bootstrap-baseline": {},
}


def _example(workflow: str) -> str:
    return (EXAMPLES / f"{workflow}.example.json").read_text(encoding="utf-8")


def _validate(workflow: str, raw: str) -> dict[str, str]:
    return validate_dispatch_config(
        cast(WorkflowName, workflow), raw, EXTERNAL_ENVIRONMENTS[workflow]
    )


@pytest.mark.parametrize("workflow", sorted(EXTERNAL_ENVIRONMENTS))
def test_documented_dispatch_examples_pass_exact_validation(workflow: str) -> None:
    values = _validate(workflow, _example(workflow))

    assert re.fullmatch(r"sha256:[0-9a-f]{64}", values["DISPATCH_CONFIG_SHA256"])
    assert all("\n" not in value for value in values.values())

    if workflow == "train":
        assert values["TRAINING_IMAGE_URI"].endswith("@sha256:" + "b" * 64)
        assert values["PREPARED_DATA_S3_URI"].startswith(
            "s3://example-artifacts-bucket/data/processed/"
        )
    elif workflow == "release":
        assert values["EVALUATION_IMAGE_URI"].endswith("@sha256:" + "3" * 64)
        assert values["BASELINE_CONFIG_PATH"] == "configs/experiments/baselines-v1.yaml"
        assert values["BASELINE_CONFIG_FILE_SHA256"] == "7" * 64
        assert values["CANDIDATE_ARTIFACT_S3_URI"] == (
            "s3://example-artifacts-bucket/runs/training-run-001/model.tar.gz"
        )


@pytest.mark.parametrize(
    ("workflow_name", "expected_inputs"),
    (
        ("train.yml", {"dispatch_config", "authorization"}),
        (
            "release.yml",
            {"dispatch_config", "allow_heldout_eval", "authorization"},
        ),
        ("bootstrap-baseline.yml", {"dispatch_config", "authorization"}),
    ),
)
def test_manual_workflows_stay_below_githubs_ten_input_limit(
    workflow_name: str, expected_inputs: set[str]
) -> None:
    source = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
    document = yaml.load(source, Loader=yaml.BaseLoader)
    inputs = document["on"]["workflow_dispatch"]["inputs"]

    assert set(inputs) == expected_inputs
    assert len(inputs) <= 10
    assert set(re.findall(r"\$\{\{\s*inputs\.([A-Za-z0-9_]+)", source)) <= expected_inputs


@pytest.mark.parametrize("workflow", sorted(EXTERNAL_ENVIRONMENTS))
def test_dispatch_config_rejects_extra_missing_and_non_string_fields(workflow: str) -> None:
    values = json.loads(_example(workflow))
    first_key = next(iter(values))
    environment = EXTERNAL_ENVIRONMENTS[workflow]

    with pytest.raises(ValueError, match="keys are not exact"):
        validate_dispatch_config(
            cast(WorkflowName, workflow),
            json.dumps({**values, "unexpected": "value"}),
            environment,
        )
    with pytest.raises(ValueError, match="keys are not exact"):
        validate_dispatch_config(
            cast(WorkflowName, workflow),
            json.dumps({key: value for key, value in values.items() if key != first_key}),
            environment,
        )
    values[first_key] = 1
    with pytest.raises(ValueError, match="must be a JSON string"):
        validate_dispatch_config(cast(WorkflowName, workflow), json.dumps(values), environment)


def test_dispatch_config_rejects_duplicate_keys_and_control_characters() -> None:
    raw = _example("train")
    duplicate = raw.replace(
        '"accelerator": "gpu",',
        '"accelerator": "gpu", "accelerator": "gpu",',
        1,
    )
    with pytest.raises(ValueError, match="duplicate key: accelerator"):
        validate_dispatch_config("train", duplicate, EXTERNAL_ENVIRONMENTS["train"])

    values = json.loads(raw)
    values["prepared_data_s3_prefix"] += "\nunsafe"
    with pytest.raises(ValueError, match="contains controls"):
        validate_dispatch_config("train", json.dumps(values), EXTERNAL_ENVIRONMENTS["train"])


def test_train_dispatch_rejects_mismatched_hardware() -> None:
    values = json.loads(_example("train"))
    values["accelerator"] = "cpu"

    with pytest.raises(ValueError, match="instance_type and accelerator do not match"):
        validate_dispatch_config("train", json.dumps(values), EXTERNAL_ENVIRONMENTS["train"])


def test_release_dispatch_rejects_unbound_baseline_and_excess_runtime() -> None:
    values = json.loads(_example("release"))
    values["strongest_baseline_id"] = "unreviewed-baseline"
    with pytest.raises(ValueError, match="absent from baseline_ids"):
        validate_dispatch_config("release", json.dumps(values), EXTERNAL_ENVIRONMENTS["release"])

    values = json.loads(_example("release"))
    values["maximum_timeout_seconds"] = "7201"
    with pytest.raises(ValueError, match="exceeds two hours"):
        validate_dispatch_config("release", json.dumps(values), EXTERNAL_ENVIRONMENTS["release"])

    values = json.loads(_example("release"))
    values["baseline_config_path"] = "configs/experiments/release-v1.yaml"
    with pytest.raises(ValueError, match="outside its allowlist"):
        validate_dispatch_config("release", json.dumps(values), EXTERNAL_ENVIRONMENTS["release"])

    values = json.loads(_example("release"))
    values["baseline_config_file_sha256"] = "unbound"
    with pytest.raises(ValueError, match="invalid format"):
        validate_dispatch_config("release", json.dumps(values), EXTERNAL_ENVIRONMENTS["release"])


def test_release_stages_an_immutable_decision_without_mutating_the_live_pointer() -> None:
    source = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    publication = source.split("PromotionPointer.model_validate_json", 1)[1]
    helper = source.split("put_promoted_immutable_or_verify_identical()", 1)[1].split(
        "while IFS= read -r -d '' file", 1
    )[0]

    decision_assignment = 'decision_key="promoted/decisions/${REPORT_ID}.json"'
    decision_call = (
        "put_promoted_immutable_or_verify_identical \\\n"
        '            promotion-pointer.json "${decision_key}" application/json'
    )
    assert decision_assignment in publication
    assert decision_call in publication
    assert publication.index(decision_assignment) < publication.index(decision_call)
    assert "--if-none-match '*'" in helper
    assert 'cmp -s "${source_file}" "${existing}"' in helper
    assert ".Metadata ==" in helper
    assert "--key promoted/current.json" not in publication
    assert "live pointer remains unchanged" in publication
    assert '--version-id "${previous_version_id}"' in source


def test_cli_exports_only_after_the_whole_dispatch_config_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "github-env"
    monkeypatch.setenv("DISPATCH_CONFIG_JSON", _example("train"))
    for name, value in EXTERNAL_ENVIRONMENTS["train"].items():
        monkeypatch.setenv(name, value)

    assert main(["--workflow", "train", "--github-env", str(output)]) == 0
    exported = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert exported["CONFIG_PATH"] == "configs/experiments/candidate-v1.yaml"
    assert exported["TRAINING_IMAGE_URI"].endswith("@sha256:" + "b" * 64)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", exported["DISPATCH_CONFIG_SHA256"])

    rejected_output = tmp_path / "rejected-github-env"
    monkeypatch.setenv("DISPATCH_CONFIG_JSON", '{"unexpected":"value"}')
    with pytest.raises(SystemExit, match="dispatch config rejected"):
        main(["--workflow", "train", "--github-env", str(rejected_output)])
    assert not rejected_output.exists()
