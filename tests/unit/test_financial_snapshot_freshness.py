from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scripts.validate_financial_snapshot import (
    EXPECTED_SOURCE,
    FinancialSnapshotError,
    build_snapshot,
    compute_receipt_sha256,
    main,
    verify_cost_preflight,
)
from search_rank.schemas.workflow import (
    BenchmarkCostPreflight,
    EvaluationCostPreflight,
    ProtectedFinancialSnapshot,
    TrainingCostPreflight,
)

ROOT = Path(__file__).resolve().parents[2]
OBSERVED_AT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
HMAC_KEY = "1" * 64
SENTINEL_SPEND = "12.3400198765"
SENTINEL_CREDIT = "87.6599801235"
AUTHORIZATION_WORKFLOW = "train"
AUTHORIZATION_COMMIT = "a" * 40
AUTHORIZATION_INPUTS = {
    "authorization": "SUBMIT ONE SAGEMAKER TRAINING JOB",
    "dispatch_config": '{"run_id":"scope-sentinel"}',
}


def protected_environment(
    observed_at: datetime = OBSERVED_AT,
    *,
    spend: str = SENTINEL_SPEND,
    credit: str = SENTINEL_CREDIT,
    authorization_workflow: str = AUTHORIZATION_WORKFLOW,
    authorization_inputs: dict[str, object] | None = None,
    authorization_commit: str = AUTHORIZATION_COMMIT,
) -> dict[str, str]:
    scope_inputs = AUTHORIZATION_INPUTS if authorization_inputs is None else authorization_inputs
    environment = {
        "FINANCIAL_SNAPSHOT_OBSERVED_AT": observed_at.isoformat(),
        "FINANCIAL_SNAPSHOT_SOURCE": EXPECTED_SOURCE,
        "FINANCIAL_SNAPSHOT_MAX_AGE_SECONDS": "21600",
        "FINANCIAL_SNAPSHOT_HMAC_KEY": HMAC_KEY,
        "CAMPAIGN_SPEND_TO_DATE_USD": spend,
        "REMAINING_APPLICABLE_CREDIT_USD": credit,
        "FINANCIAL_SNAPSHOT_AUTHORIZATION_WORKFLOW": authorization_workflow,
        "FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON": json.dumps(scope_inputs),
        "FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA": authorization_commit,
        "CAMPAIGN_BUDGET_USD": "40",
        "REQUIRED_CREDIT_RESERVE_USD": "40",
        "MAXIMUM_OUT_OF_POCKET_USD": "0",
        "FINANCIAL_RESERVATION_MAX_USD": "1.00",
        "FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD": "0",
        "FINANCIAL_RESERVATION_CPU_HOURS": "1",
        "FINANCIAL_RESERVATION_GPU_HOURS": "0",
        "FINANCIAL_CPU_HOURS_USED_TO_DATE": "2",
        "FINANCIAL_GPU_HOURS_USED_TO_DATE": "3",
    }
    environment["FINANCIAL_SNAPSHOT_RECEIPT_SHA256"] = compute_receipt_sha256(environment)
    return environment


def training_cost(snapshot: ProtectedFinancialSnapshot) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "training_cost_preflight",
        "region": "us-east-1",
        "instance_type": "ml.g4dn.xlarge",
        "accelerator": "gpu",
        "maximum_runtime_seconds": 3600,
        "on_demand_hourly_upper_bound_usd": "1.00",
        "maximum_job_estimate_usd": "1.00",
        "campaign_and_credit_guard_passed": True,
        "credit_balance_redacted_from_public_evidence": True,
        "required_credit_reserve_usd": "40",
        "maximum_out_of_pocket_usd": "0",
        "pricing_basis": "live AWS Price List response; highest matching hourly dimension",
        "financial_snapshot": snapshot.model_dump(mode="json"),
    }


def evaluation_cost(snapshot: ProtectedFinancialSnapshot) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "evaluation_cost_preflight",
        "guard_passed": True,
        "region": "us-east-1",
        "instance_type": "ml.m5.xlarge",
        "independent_processing_job_count": 2,
        "maximum_runtime_seconds_per_job": 7200,
        "maximum_total_instance_hours": "4",
        "on_demand_hourly_upper_bound_usd": "1.00",
        "maximum_job_estimate_usd": "4.00",
        "required_credit_reserve_usd": "40",
        "maximum_out_of_pocket_usd": "0",
        "financial_snapshot": snapshot.model_dump(mode="json"),
    }


def benchmark_cost(snapshot: ProtectedFinancialSnapshot) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "benchmark_cost_preflight",
        "status": "passed",
        "checked_at": OBSERVED_AT.isoformat(),
        "benchmark_run_id": "github-123-attempt-1",
        "release_id": "release-1",
        "model_id": "candidate-v1",
        "region": "us-east-1",
        "public_origin": "https://example.cloudfront.net",
        "maximum_out_of_pocket_usd": "0",
        "campaign_envelope_usd": "40",
        "required_credit_reserve_usd": "40",
        "conservative_benchmark_allowance_usd": "0.50",
        "heldout_access_enabled": False,
        "sensitive_balance_values_recorded": False,
        "financial_snapshot": snapshot.model_dump(mode="json"),
    }


def test_protected_snapshot_accepts_the_boundary_and_records_no_balances() -> None:
    snapshot = build_snapshot(
        protected_environment(),
        now=OBSERVED_AT + timedelta(hours=6),
    )

    assert snapshot.age_seconds_at_validation == 21_600
    assert snapshot.receipt_binding_algorithm == "hmac-sha256-v2"
    assert snapshot.authorization_workflow == AUTHORIZATION_WORKFLOW
    assert snapshot.authorization_commit_sha == AUTHORIZATION_COMMIT
    assert snapshot.authorization_input_sha256.startswith("sha256:")
    assert snapshot.authorization_operation_id.startswith("sha256:")
    assert snapshot.authorization_reservation_sha256.startswith("sha256:")
    assert snapshot.campaign_spend_to_date_redacted is True
    assert snapshot.remaining_applicable_credit_redacted is True
    serialized = snapshot.model_dump_json()
    assert SENTINEL_SPEND not in serialized
    assert SENTINEL_CREDIT not in serialized
    assert HMAC_KEY not in serialized


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("CAMPAIGN_SPEND_TO_DATE_USD", "Infinity"),
        ("REMAINING_APPLICABLE_CREDIT_USD", "Infinity"),
        ("CAMPAIGN_SPEND_TO_DATE_USD", "NaN"),
        ("REMAINING_APPLICABLE_CREDIT_USD", "NaN"),
    ),
)
def test_protected_snapshot_rejects_non_finite_private_values(name: str, value: str) -> None:
    environment = protected_environment()
    environment[name] = value
    with pytest.raises(FinancialSnapshotError, match="finite"):
        build_snapshot(environment, now=OBSERVED_AT)


@pytest.mark.parametrize(
    ("name", "replacement"),
    (
        ("CAMPAIGN_SPEND_TO_DATE_USD", "12.3400198766"),
        ("REMAINING_APPLICABLE_CREDIT_USD", "87.6599801234"),
        ("FINANCIAL_SNAPSHOT_OBSERVED_AT", "2026-09-02T12:00:01+00:00"),
        ("FINANCIAL_SNAPSHOT_SOURCE", "another_source"),
        ("FINANCIAL_SNAPSHOT_AUTHORIZATION_WORKFLOW", "release"),
        (
            "FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON",
            '{"authorization":"SUBMIT ONE SAGEMAKER TRAINING JOB","dispatch_config":"changed"}',
        ),
        ("FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA", "b" * 40),
        ("FINANCIAL_RESERVATION_MAX_USD", "2.00"),
        ("FINANCIAL_RESERVATION_REMAINING_COMMITTED_USD", "3.00"),
        ("FINANCIAL_RESERVATION_CPU_HOURS", "4"),
        ("FINANCIAL_RESERVATION_GPU_HOURS", "5"),
        ("FINANCIAL_CPU_HOURS_USED_TO_DATE", "6"),
        ("FINANCIAL_GPU_HOURS_USED_TO_DATE", "7"),
    ),
)
def test_receipt_binds_every_exact_private_snapshot_field(name: str, replacement: str) -> None:
    environment = protected_environment()
    environment[name] = replacement
    with pytest.raises(FinancialSnapshotError):
        build_snapshot(environment, now=OBSERVED_AT + timedelta(seconds=2))


@pytest.mark.parametrize(
    ("workflow", "input_name", "nested_dispatch"),
    (
        ("train", "cpu_hours_used_to_date", True),
        ("train", "gpu_hours_used_to_date", True),
        ("train", "estimated_remaining_non_job_usd", True),
        ("train", "declared_job_cost_cap_usd", True),
        ("release", "cpu_hours_used_to_date", True),
        ("release", "estimated_remaining_non_job_usd", True),
        ("release", "declared_job_cost_cap_usd", True),
        ("benchmark-serving", "release_id", False),
        ("deploy", "action", False),
    ),
)
def test_receipt_rejects_cost_state_or_operation_input_replay(
    workflow: str, input_name: str, nested_dispatch: bool
) -> None:
    if nested_dispatch:
        inputs: dict[str, object] = {
            "authorization": "approved",
            "dispatch_config": json.dumps({input_name: "0"}, separators=(",", ":")),
        }
        replacement = {
            **inputs,
            "dispatch_config": json.dumps({input_name: "999"}, separators=(",", ":")),
        }
    else:
        inputs = {"authorization": "approved", input_name: "original"}
        replacement = {**inputs, input_name: "changed"}

    environment = protected_environment(
        authorization_workflow=workflow,
        authorization_inputs=inputs,
    )
    original_receipt = environment["FINANCIAL_SNAPSHOT_RECEIPT_SHA256"]
    environment["FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON"] = json.dumps(replacement)

    assert compute_receipt_sha256(environment) != original_receipt
    with pytest.raises(FinancialSnapshotError, match="authorization scope"):
        build_snapshot(environment, now=OBSERVED_AT)


@pytest.mark.parametrize(
    ("environment", "checked_at", "message"),
    (
        (protected_environment(), OBSERVED_AT + timedelta(hours=6, microseconds=1), "stale"),
        (protected_environment(), OBSERVED_AT - timedelta(seconds=1), "future"),
        (
            {**protected_environment(), "FINANCIAL_SNAPSHOT_MAX_AGE_SECONDS": "86400"},
            OBSERVED_AT,
            "six hours",
        ),
        (
            {
                **protected_environment(),
                "FINANCIAL_SNAPSHOT_RECEIPT_SHA256": "sha256:" + "0" * 64,
            },
            OBSERVED_AT,
            "non-placeholder",
        ),
    ),
)
def test_protected_snapshot_fails_closed(
    environment: dict[str, str], checked_at: datetime, message: str
) -> None:
    with pytest.raises(FinancialSnapshotError, match=message):
        build_snapshot(environment, now=checked_at)


def test_snapshot_schema_rejects_inconsistent_age_evidence() -> None:
    payload = build_snapshot(
        protected_environment(), now=OBSERVED_AT + timedelta(minutes=5)
    ).model_dump(mode="json")
    payload["age_seconds_at_validation"] = 299

    with pytest.raises(ValidationError, match="age evidence is inconsistent"):
        ProtectedFinancialSnapshot.model_validate(payload)


def test_cost_preflight_contracts_require_snapshot_provenance() -> None:
    snapshot = build_snapshot(protected_environment(), now=OBSERVED_AT)
    assert (
        TrainingCostPreflight.model_validate(training_cost(snapshot)).financial_snapshot == snapshot
    )
    assert (
        EvaluationCostPreflight.model_validate(evaluation_cost(snapshot)).financial_snapshot
        == snapshot
    )
    assert (
        BenchmarkCostPreflight.model_validate(benchmark_cost(snapshot)).financial_snapshot
        == snapshot
    )

    training = training_cost(snapshot)
    training.pop("financial_snapshot")
    with pytest.raises(ValidationError):
        TrainingCostPreflight.model_validate(training)

    evaluation = evaluation_cost(snapshot)
    evaluation.pop("financial_snapshot")
    with pytest.raises(ValidationError):
        EvaluationCostPreflight.model_validate(evaluation)

    benchmark = benchmark_cost(snapshot)
    benchmark.pop("financial_snapshot")
    with pytest.raises(ValidationError):
        BenchmarkCostPreflight.model_validate(benchmark)

    for payload in (training_cost(snapshot), evaluation_cost(snapshot), benchmark_cost(snapshot)):
        serialized = json.dumps(payload, sort_keys=True)
        assert SENTINEL_SPEND not in serialized
        assert SENTINEL_CREDIT not in serialized
        assert HMAC_KEY not in serialized


@pytest.mark.parametrize("payload_factory", (training_cost, evaluation_cost, benchmark_cost))
def test_submission_revalidation_binds_receipt_and_rechecks_ttl(
    tmp_path: Path,
    payload_factory: Callable[[ProtectedFinancialSnapshot], dict[str, object]],
) -> None:
    snapshot = build_snapshot(protected_environment(), now=OBSERVED_AT + timedelta(minutes=1))
    path = tmp_path / "cost-preflight.json"
    path.write_text(json.dumps(payload_factory(snapshot)), encoding="utf-8")

    assert (
        verify_cost_preflight(
            path,
            protected_environment(),
            now=OBSERVED_AT + timedelta(hours=6),
        ).receipt_sha256
        == protected_environment()["FINANCIAL_SNAPSHOT_RECEIPT_SHA256"]
    )
    with pytest.raises(FinancialSnapshotError, match="stale"):
        verify_cost_preflight(
            path,
            protected_environment(),
            now=OBSERVED_AT + timedelta(hours=6, seconds=1),
        )
    with pytest.raises(FinancialSnapshotError, match="not bound"):
        verify_cost_preflight(
            path,
            {
                **protected_environment(),
                "FINANCIAL_SNAPSHOT_RECEIPT_SHA256": "sha256:" + "b" * 64,
            },
            now=OBSERVED_AT + timedelta(minutes=2),
        )


def test_cli_failure_message_does_not_echo_protected_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive_receipt = "not-a-public-receipt"
    environment = {
        **protected_environment(),
        "FINANCIAL_SNAPSHOT_RECEIPT_SHA256": sensitive_receipt,
    }

    assert main(["emit", "--output", "unused.json"], environment=environment, now=OBSERVED_AT) == 1
    error = capsys.readouterr().err
    assert sensitive_receipt not in error
    assert SENTINEL_SPEND not in error
    assert SENTINEL_CREDIT not in error
    assert HMAC_KEY not in error


def test_receipt_cli_emits_only_the_keyed_commitment(capsys: pytest.CaptureFixture[str]) -> None:
    environment = protected_environment()
    assert main(["receipt"], environment=environment, now=OBSERVED_AT) == 0
    output = capsys.readouterr().out.strip()
    assert output == environment["FINANCIAL_SNAPSHOT_RECEIPT_SHA256"]
    assert SENTINEL_SPEND not in output
    assert SENTINEL_CREDIT not in output
    assert HMAC_KEY not in output


def test_scope_cli_emits_hashes_but_not_raw_operation_inputs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment = protected_environment()
    assert main(["scope"], environment=environment, now=OBSERVED_AT) == 0
    output = capsys.readouterr().out
    scope = json.loads(output)
    assert scope["authorization_workflow"] == AUTHORIZATION_WORKFLOW
    assert scope["authorization_commit_sha"] == AUTHORIZATION_COMMIT
    assert "scope-sentinel" not in output
    assert SENTINEL_SPEND not in output
    assert SENTINEL_CREDIT not in output
    assert HMAC_KEY not in output


def test_costed_workflows_revalidate_at_the_cost_incurrence_boundary() -> None:
    train = (ROOT / ".github/workflows/train.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    benchmark = (ROOT / ".github/workflows/benchmark-serving.yml").read_text(encoding="utf-8")

    for source in (train, release, benchmark):
        assert "secrets.AWS_FINANCIAL_SNAPSHOT_OBSERVED_AT" in source
        assert "secrets.AWS_FINANCIAL_SNAPSHOT_RECEIPT_SHA256" in source
        assert "secrets.AWS_FINANCIAL_SNAPSHOT_HMAC_KEY" in source
        assert 'FINANCIAL_SNAPSHOT_MAX_AGE_SECONDS: "21600"' in source
        assert 'FINANCIAL_SNAPSHOT_SOURCE: "aws_billing_and_cost_management_console"' in source
        assert '"financial_snapshot"' in source

    train_create = train.index("aws sagemaker create-training-job")
    assert train.rindex("validate_financial_snapshot.py verify", 0, train_create) < train_create

    release_create = release.index("aws sagemaker create-processing-job")
    function_start = release.rindex("submit_and_wait()", 0, release_create)
    assert (
        release.rindex("validate_financial_snapshot.py verify", function_start, release_create)
        < release_create
    )

    matrix = benchmark.split("- name: Execute the fixed public performance matrix", 1)[1]
    assert matrix.index("validate_financial_snapshot.py verify") < matrix.index("python - <<'PY'")


def _workflow_job(path: str, job: str, next_job: str | None = None) -> str:
    source = (ROOT / ".github/workflows" / path).read_text(encoding="utf-8")
    body = source.split(f"\n  {job}:\n", 1)[1]
    if next_job is not None:
        body = body.split(f"\n  {next_job}:\n", 1)[0]
    return body


def _workflow_step(path: str, job: str, step_name: str) -> str:
    payload = yaml.safe_load((ROOT / ".github/workflows" / path).read_text(encoding="utf-8"))
    steps = payload["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, (path, job, step_name)
    return matches[0]


def _assert_every_boundary_is_immediately_guarded(script: str, boundary: str) -> None:
    lines = script.splitlines()
    positions = [index for index, line in enumerate(lines) if boundary in line]
    assert positions, boundary
    for position in positions:
        preceding_command = "\n".join(lines[max(0, position - 4) : position])
        assert "validate_financial_snapshot.py" in preceding_command, (
            boundary,
            lines[max(0, position - 6) : position + 2],
        )


@pytest.mark.parametrize(
    ("workflow", "job", "step_name", "boundary"),
    (
        (
            "baseline.yml",
            "baseline",
            "Publish immutable validation evidence and bootstrap handoff",
            "aws s3api put-object",
        ),
        (
            "bootstrap-baseline.yml",
            "publish",
            "Publish the immutable baseline bundle and create the initial pointer",
            "aws s3api put-object",
        ),
        (
            "build-images.yml",
            "build-and-push",
            "Build, push, and capture immutable digests",
            "docker push",
        ),
        (
            "freeze-trial-selection.yml",
            "freeze",
            "Publish one immutable zero-test-access selection artifact",
            "aws s3api put-object",
        ),
        (
            "prepare-data.yml",
            "prepare-and-publish",
            "Publish and verify the content-addressed dataset and sanitized handoff",
            "aws s3api put-object",
        ),
        (
            "infrastructure.yml",
            "terraform",
            "Format check, initialize, validate, and plan",
            "terraform plan",
        ),
        (
            "infrastructure.yml",
            "terraform",
            "Apply the exact reviewed plan",
            "terraform apply",
        ),
        (
            "bootstrap-infrastructure.yml",
            "bootstrap",
            "Create or reproduce the exact plan, then optionally apply and migrate state",
            "aws s3api put-object",
        ),
        (
            "bootstrap-infrastructure.yml",
            "bootstrap",
            "Create or reproduce the exact plan, then optionally apply and migrate state",
            "terraform apply",
        ),
        (
            "bootstrap-infrastructure.yml",
            "bootstrap",
            "Create or reproduce the exact plan, then optionally apply and migrate state",
            "terraform init \\",
        ),
        (
            "train.yml",
            "submit",
            "Upload frozen configuration and submit exactly one job",
            "aws s3api put-object",
        ),
        (
            "train.yml",
            "submit",
            "Upload frozen configuration and submit exactly one job",
            "aws sagemaker create-training-job",
        ),
        (
            "train.yml",
            "submit",
            "Verify and record immutable candidate release inputs",
            "aws s3api put-object",
        ),
        (
            "train.yml",
            "submit",
            "Verify and record immutable candidate release inputs",
            "aws s3api put-object-tagging",
        ),
        (
            "train.yml",
            "submit",
            "Mark bounded checkpoints for lifecycle expiration",
            "aws s3api put-object-tagging",
        ),
    ),
)
def test_non_overlapping_workflow_boundaries_are_path_local_and_immediately_guarded(
    workflow: str,
    job: str,
    step_name: str,
    boundary: str,
) -> None:
    _assert_every_boundary_is_immediately_guarded(
        _workflow_step(workflow, job, step_name), boundary
    )


def test_exact_existing_training_job_reuse_revalidates_the_bound_snapshot() -> None:
    script = _workflow_step(
        "train.yml", "submit", "Upload frozen configuration and submit exactly one job"
    )
    reuse = script.index('echo "Reusing exact existing SageMaker training job')
    validation = script.rindex("validate_financial_snapshot.py verify", 0, reuse)
    branch = script.rindex("validate_existing_training_job", 0, reuse)
    assert branch < validation < reuse


@pytest.mark.parametrize(
    ("step_name", "boundary"),
    (
        ("Run two separately counted clean held-out Processing jobs", "aws s3api put-object"),
        (
            "Run two separately counted clean held-out Processing jobs",
            "aws sagemaker create-processing-job",
        ),
        (
            "Verify both clean outputs, bind them, and apply the promotion decision",
            "aws s3api put-object",
        ),
        ("Build and publish the checksummed held-out outcome bundle", "aws s3api put-object"),
    ),
)
def test_release_write_boundaries_are_path_local_and_immediately_guarded(
    step_name: str, boundary: str
) -> None:
    _assert_every_boundary_is_immediately_guarded(
        _workflow_step("release.yml", "evaluate-and-promote", step_name), boundary
    )


def test_each_exact_existing_processing_job_reuse_revalidates_the_bound_snapshot() -> None:
    script = _workflow_step(
        "release.yml",
        "evaluate-and-promote",
        "Run two separately counted clean held-out Processing jobs",
    )
    reuse = script.index('echo "Reusing exact existing held-out Processing job')
    validation = script.rindex("validate_financial_snapshot.py verify", 0, reuse)
    branch = script.rindex('case "${existing_status}"', 0, reuse)
    assert branch < validation < reuse
    assert 'reserve_counter "${second_counter}" 2\nsubmit_and_wait 2' in script


def test_benchmark_matrix_and_publication_are_independently_revalidated() -> None:
    matrix = _workflow_step(
        "benchmark-serving.yml", "benchmark", "Execute the fixed public performance matrix"
    )
    _assert_every_boundary_is_immediately_guarded(matrix, "python - <<'PY'")
    publication = _workflow_step(
        "benchmark-serving.yml", "benchmark", "Publish the immutable validated performance evidence"
    )
    _assert_every_boundary_is_immediately_guarded(publication, "aws s3api put-object")


def test_deploy_installs_a_path_wide_gate_before_any_aws_cli_mutation() -> None:
    payload = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    mutation_pattern = re.compile(
        r"\baws\s+(?:cloudfront\s+create-invalidation|ecr\s+put-image|"
        r"lambda\s+(?:put-function-concurrency|update-alias)|s3\s+(?:cp|rm|sync)|"
        r"s3api\s+(?:put-object|put-object-tagging)|"
        r"sagemaker\s+(?:create-processing-job|create-training-job))\b"
    )
    for job_name in ("deploy", "rollback"):
        steps = payload["jobs"][job_name]["steps"]
        install_positions = [
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Install the protected AWS mutation gate"
        ]
        assert len(install_positions) == 1
        install_position = install_positions[0]
        install_script = steps[install_position]["run"]
        assert "scripts/aws_financial_gate.sh" in install_script
        assert "GITHUB_PATH" in install_script
        for index, step in enumerate(steps):
            if mutation_pattern.search(step.get("run", "")):
                assert index > install_position, (job_name, step.get("name"))

    wrapper = (ROOT / "scripts/aws_financial_gate.sh").read_text(encoding="utf-8")
    for command in (
        "cloudfront create-invalidation",
        "ecr put-image",
        "lambda put-function-concurrency",
        "lambda update-alias",
        "s3 rm",
        "s3api put-object",
        "s3api put-object-tagging",
        "sagemaker create-processing-job",
        "sagemaker create-training-job",
    ):
        assert command in wrapper
    assert '"s3 cp" | "s3 sync"' in wrapper
    assert "validate_financial_snapshot.py" in wrapper


@pytest.mark.parametrize(
    ("job", "step_name", "boundary"),
    (
        (
            "deploy",
            "Measure the newly published candidate's first on-demand invocation",
            'cold_result="$(curl',
        ),
        (
            "deploy",
            "Run the candidate API contract, error-rate, and primary latency gates",
            "assert_200 /healthz",
        ),
        (
            "deploy",
            "Run the candidate API contract, error-rate, and primary latency gates",
            "for warmup in",
        ),
        ("deploy", "Build and stage the immutable static release", "curl --fail"),
        (
            "deploy",
            "Browser-smoke the staged static candidate through CloudFront",
            "staged_health_verified=0",
        ),
        ("deploy", "Browser-smoke the staged static candidate through CloudFront", "node - <<'JS'"),
        (
            "deploy",
            "Verify the activated API and complete browser flow through CloudFront",
            "python ../scripts/smoke_test.py",
        ),
        (
            "deploy",
            "Verify the activated API and complete browser flow through CloudFront",
            "production_health_verified=0",
        ),
        (
            "deploy",
            "Verify the activated API and complete browser flow through CloudFront",
            "node - <<'JS'",
        ),
        (
            "deploy",
            "Publish deployment evidence only after production verification passes",
            "curl --fail",
        ),
        (
            "rollback",
            "Restore model pointer, Lambda alias, and static release",
            "public_index_ready=0",
        ),
        ("rollback", "Restore model pointer, Lambda alias, and static release", "node - <<'JS'"),
    ),
)
def test_deploy_request_matrices_are_path_local_and_immediately_guarded(
    job: str, step_name: str, boundary: str
) -> None:
    _assert_every_boundary_is_immediately_guarded(
        _workflow_step("deploy.yml", job, step_name), boundary
    )


def test_every_protected_balance_parser_rejects_non_finite_decimals() -> None:
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        source = path.read_text(encoding="utf-8")
        if "AWS_REMAINING_APPLICABLE_CREDIT_USD" not in source:
            continue
        functions = source.split("def amount(name: str) -> Decimal:")[1:]
        assert functions, path.name
        for function in functions:
            body = function.split("return value", 1)[0]
            assert "not value.is_finite()" in body, path.name


def test_every_consuming_job_configures_the_private_hmac_key() -> None:
    expected_workflows = {
        "baseline.yml": "baseline",
        "benchmark-serving.yml": "benchmark-serving",
        "bootstrap-baseline.yml": "bootstrap-baseline",
        "bootstrap-infrastructure.yml": "bootstrap-infrastructure",
        "build-images.yml": "build-images",
        "deploy.yml": "deploy",
        "freeze-trial-selection.yml": "freeze-trial-selection",
        "infrastructure.yml": "infrastructure",
        "prepare-data.yml": "prepare-data",
        "release.yml": "release",
        "train.yml": "train",
    }
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in payload.get("jobs", {}).items():
            environment = job.get("env", {})
            if "REMAINING_APPLICABLE_CREDIT_USD" not in environment:
                continue
            assert environment.get("FINANCIAL_SNAPSHOT_HMAC_KEY") == (
                "${{ secrets.AWS_FINANCIAL_SNAPSHOT_HMAC_KEY }}"
            ), (path.name, job_name)
            assert (
                environment.get("FINANCIAL_SNAPSHOT_AUTHORIZATION_WORKFLOW")
                == (expected_workflows[path.name])
            ), (path.name, job_name)
            assert environment.get("FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON") == (
                "${{ toJSON(inputs) }}"
            ), (path.name, job_name)
            assert environment.get("FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA") == (
                "${{ github.sha }}"
            ), (path.name, job_name)
        if path.name in expected_workflows:
            assert payload.get("concurrency") == {
                "group": "aws-financial-operations",
                "cancel-in-progress": False,
            }, path.name


def _assert_protected_snapshot_environment(source: str) -> None:
    assert "secrets.AWS_FINANCIAL_SNAPSHOT_OBSERVED_AT" in source
    assert "secrets.AWS_FINANCIAL_SNAPSHOT_RECEIPT_SHA256" in source
    assert "secrets.AWS_FINANCIAL_SNAPSHOT_HMAC_KEY" in source
    assert "FINANCIAL_SNAPSHOT_AUTHORIZATION_WORKFLOW" in source
    assert "FINANCIAL_SNAPSHOT_AUTHORIZATION_INPUTS_JSON" in source
    assert "FINANCIAL_SNAPSHOT_AUTHORIZATION_COMMIT_SHA" in source
    assert 'FINANCIAL_SNAPSHOT_MAX_AGE_SECONDS: "21600"' in source
    assert 'FINANCIAL_SNAPSHOT_SOURCE: "aws_billing_and_cost_management_console"' in source


@pytest.mark.parametrize(
    ("workflow", "job", "next_job", "first_write"),
    [
        ("bootstrap-infrastructure.yml", "bootstrap", None, "terraform apply"),
        ("infrastructure.yml", "terraform", None, "terraform apply"),
        ("build-images.yml", "build-and-push", None, "docker push"),
        ("prepare-data.yml", "prepare-and-publish", None, "aws s3api put-object"),
        ("baseline.yml", "baseline", None, "aws s3api put-object"),
        ("bootstrap-baseline.yml", "publish", None, "aws s3api put-object"),
        ("freeze-trial-selection.yml", "freeze", None, "aws s3api put-object"),
        ("deploy.yml", "deploy", "rollback", "aws ecr put-image"),
    ],
)
def test_every_cost_secret_workflow_revalidates_before_its_first_new_aws_write(
    workflow: str,
    job: str,
    next_job: str | None,
    first_write: str,
) -> None:
    source = _workflow_job(workflow, job, next_job)
    _assert_protected_snapshot_environment(source)

    write_offset = source.index(first_write)
    assert source.rindex("validate_financial_snapshot.py emit", 0, write_offset) < write_offset


def test_deploy_revalidates_every_branch_that_can_be_the_first_new_write() -> None:
    deploy = _workflow_job("deploy.yml", "deploy", "rollback")

    for first_write in (
        "aws ecr put-image",
        'docker push "${SERVE_REPOSITORY}:${release_tag}"',
        "terraform apply -input=false -auto-approve deploy.tfplan",
        "terraform apply -input=false -auto-approve public.tfplan",
    ):
        write_offset = deploy.index(first_write)
        assert deploy.rindex("validate_financial_snapshot.py emit", 0, write_offset) < write_offset


def test_manual_rollback_revalidates_immediately_before_the_live_transition() -> None:
    rollback = _workflow_job("deploy.yml", "rollback")
    _assert_protected_snapshot_environment(rollback)

    transition_offset = rollback.index("transition_started=1")
    validation_offset = rollback.rindex("validate_financial_snapshot.py emit", 0, transition_offset)
    first_live_write = rollback.index("aws lambda update-alias", transition_offset)
    assert validation_offset < transition_offset < first_live_write
