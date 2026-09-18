from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "dev-teardown.yml"


def _workflow() -> tuple[str, dict[str, object]]:
    source = WORKFLOW.read_text(encoding="utf-8")
    return source, yaml.load(source, Loader=yaml.BaseLoader)


def test_workflow_has_one_fixed_dev_scope_and_two_dispatch_phases() -> None:
    source, payload = _workflow()
    inputs = payload["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "approved_plan_sha256",
        "authorization",
        "operation",
        "reviewed_commit_sha",
    }
    assert inputs["operation"]["options"] == ["plan", "destroy"]
    assert "environment" not in inputs
    assert payload["env"]["DEPLOYMENT_ENVIRONMENT"] == "dev"
    assert payload["env"]["AWS_REGION"] == "us-east-1"
    job = payload["jobs"]["lifecycle"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["environment"] == "aws-dev-lifecycle"
    assert payload["concurrency"] == {
        "group": "aws-financial-operations",
        "cancel-in-progress": "false",
    }
    assert 'test "${AUTHORIZATION}" = "DESTROY DISPOSABLE DEV"' in source
    assert 'test "${REVIEWED_COMMIT_SHA}" = "${GITHUB_SHA}"' in source
    assert 'test "$(git rev-parse refs/remotes/origin/main)" = "${REVIEWED_COMMIT_SHA}"' in source
    assert "infra/terraform/environments/prod" not in source
    assert "product-search-ranking/prod/terraform.tfstate" not in source


def test_live_role_and_reproduced_plan_are_attested_before_any_destructive_write() -> None:
    source, payload = _workflow()
    role_attestation = source.index("Attest the external dev-only lifecycle role")
    active_jobs = source.index("Prove no project SageMaker job is active")
    plan = source.index("terraform plan -destroy")
    bucket_cleanup = source.index("empty_versioned_dev_bucket.py")
    repository_cleanup = source.index("empty_dev_repositories.py")
    apply = source.index("terraform apply -input=false -auto-approve destroy.tfplan")

    assert role_attestation < active_jobs < plan < bucket_cleanup < repository_cleanup < apply
    assert "build_dev_lifecycle_policy" in source[role_attestation:plan]
    assert "build_trust" in source[role_attestation:plan]
    assert 'inline_names != ["destroy-only-disposable-dev"]' in source[role_attestation:plan]
    assert "attached != []" in source[role_attestation:plan]
    assert 'role.get("PermissionsBoundary") is not None' in source[role_attestation:plan]
    assert "dev_teardown_contract.py plan" in source
    assert 'test "${plan_sha256}" = "${APPROVED_PLAN_SHA256}"' in source
    assert "> destroy-plan.private.log 2>&1" in source
    assert "> destroy-apply.private.log 2>&1" in source
    assert "> cleanup.private.log 2>&1" in source
    assert payload["permissions"] == {"contents": "read", "id-token": "write"}
    credential_steps = [
        step
        for step in payload["jobs"]["lifecycle"]["steps"]
        if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")
    ]
    assert len(credential_steps) == 1
    assert credential_steps[0]["with"]["role-to-assume"] == (
        "${{ vars.AWS_DEV_LIFECYCLE_ROLE_ARN }}"
    )


def test_only_sanitized_count_evidence_is_uploaded() -> None:
    source, payload = _workflow()
    upload = next(
        step
        for step in payload["jobs"]["lifecycle"]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    paths = set(upload["with"]["path"].splitlines())
    assert paths == {
        "infra/terraform/environments/dev/artifact-bucket-cleanup.json",
        "infra/terraform/environments/dev/dev-teardown-absence.json",
        "infra/terraform/environments/dev/dev-teardown-evidence.json",
        "infra/terraform/environments/dev/dev-teardown-plan.json",
        "infra/terraform/environments/dev/dev-teardown-plan.sha256",
        "infra/terraform/environments/dev/repository-cleanup.json",
        "infra/terraform/environments/dev/site-bucket-cleanup.json",
    }
    assert upload["if"] == "always()"
    assert not any(
        forbidden in path
        for path in paths
        for forbidden in ("private", "tfplan", "terraform.tfstate")
    )
    assert not any("private.log" in path for path in paths)
    assert "collect_dev_teardown_absence.py" in source
    assert "dev_teardown_contract.py evidence" in source
    assert "fr_cloud_009_complete=false" not in source
    assert "external lifecycle role is removed" in source
