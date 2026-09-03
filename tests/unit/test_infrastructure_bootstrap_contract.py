from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from scripts.render_bootstrap_iam import (
    APPROVED_BOUNDARY_WILDCARDS,
    BOUNDARY_NAME,
    PROJECT,
    SEED_ROLE_NAME,
    STATE_BUCKET_READ_ACTIONS,
    STATE_ROLE_NAME,
    boundary_name,
    build_boundary,
    build_platform_seed_policy,
    build_state_policy,
    build_trust,
    seed_role_name,
)

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_ID = "123456789012"
OWNER = "ArmanM1"
OWNER_ID = "85960887"
REPOSITORY_ID = "1355153874"


def _statement(document: dict[str, object], sid: str) -> dict[str, object]:
    statements = document["Statement"]
    assert isinstance(statements, list)
    return next(statement for statement in statements if statement.get("Sid") == sid)


def _actions(document: dict[str, object]) -> set[str]:
    result: set[str] = set()
    statements = document["Statement"]
    assert isinstance(statements, list)
    for statement in statements:
        actions = statement["Action"]
        result.update([actions] if isinstance(actions, str) else actions)
    return result


def test_external_boundaries_are_environment_exact_and_forbid_identity_or_bucket_policy_mutation() -> (
    None
):
    mutation_actions = {
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:PutRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
        "iam:UpdateRole",
    }
    documents = {
        environment: build_boundary(ACCOUNT_ID, environment) for environment in ("dev", "prod")
    }

    for environment, boundary in documents.items():
        compact = json.dumps(boundary, separators=(",", ":"), sort_keys=True)
        actions = _actions(boundary)
        wildcards = {action for action in actions if "*" in action}
        deny = _statement(boundary, "DenyArtifactPolicy")

        assert len(compact) <= 6144
        assert wildcards <= APPROVED_BOUNDARY_WILDCARDS
        assert "*" not in actions
        assert mutation_actions.isdisjoint(actions)
        assert deny["Effect"] == "Deny"
        assert set(deny["Action"]) == {"s3:DeleteBucketPolicy", "s3:PutBucketPolicy"}
        assert deny["Resource"] == [
            f"arn:aws:s3:::{PROJECT}-{environment}-{ACCOUNT_ID}-us-east-1-artifacts"
        ]
        serialized = json.dumps(boundary)
        assert f"/{PROJECT}/{environment}/terraform.tfstate" in serialized
        assert f"{PROJECT}-{environment}-" in serialized
        assert "/aws/sagemaker/TrainingJobs" not in serialized
        assert "/aws/sagemaker/ProcessingJobs" not in serialized
        assert f"{PROJECT}-{environment}-sagemaker-training-failure" in serialized
        assert f"{PROJECT}-{environment}-sagemaker-processing-failure" in serialized

    assert documents["dev"] != documents["prod"]
    assert boundary_name("dev") == f"{PROJECT}-dev-permissions-boundary"
    assert boundary_name("prod") == f"{PROJECT}-prod-permissions-boundary"


def test_boundary_ceiling_covers_every_project_identity_action() -> None:
    boundary_actions = _actions(build_boundary(ACCOUNT_ID))
    iam = (ROOT / "infra/terraform/modules/platform/iam.tf").read_text(encoding="utf-8")
    identity_actions = set(re.findall(r'"([a-z0-9-]+:[A-Za-z0-9*]+)"', iam))
    identity_actions = {
        action
        for action in identity_actions
        if not action.startswith(("aws:", "sts:"))
        and action not in {"iam:PassedToService", "iam:PermissionsBoundary", "s3:prefix"}
    }

    uncovered = {
        action
        for action in identity_actions
        if not any(fnmatchcase(action, ceiling) for ceiling in boundary_actions)
    }
    assert uncovered == set()


def test_platform_seed_is_non_self_modifiable_and_boundary_constrained() -> None:
    policy = build_platform_seed_policy(ACCOUNT_ID)
    compact = json.dumps(policy, separators=(",", ":"), sort_keys=True)
    boundary_arn = f"arn:aws:iam::{ACCOUNT_ID}:policy/{BOUNDARY_NAME}"
    seed_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{SEED_ROLE_NAME}"

    assert len(compact) <= 10240
    assert not _actions(policy) & {
        "iam:AttachRolePolicy",
        "iam:CreatePolicy",
        "iam:CreatePolicyVersion",
        "iam:DeletePolicy",
        "iam:DeleteRolePermissionsBoundary",
        "iam:SetDefaultPolicyVersion",
    }
    assert not _actions(policy) & {"s3:DeleteBucketPolicy", "s3:PutBucketPolicy"}
    role_creation = _statement(policy, "CreateOrBoundExactProjectRoles")
    assert set(role_creation["Action"]) == {"iam:CreateRole", "iam:PutRolePermissionsBoundary"}
    assert role_creation["Condition"] == {"StringEquals": {"iam:PermissionsBoundary": boundary_arn}}
    self_audit = _statement(policy, "AuditOnlyThisSeedRole")
    assert self_audit["Resource"] == [seed_arn]
    assert set(self_audit["Action"]) == {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
    }
    boundary_audit = _statement(policy, "AuditOnlyEnvironmentBoundary")
    assert boundary_audit["Resource"] == [boundary_arn]
    assert set(boundary_audit["Action"]) == {"iam:GetPolicy", "iam:GetPolicyVersion"}

    allowed_global_reads = {
        "cloudfront:DescribeFunction",
        "cloudfront:GetCachePolicy",
        "cloudfront:GetDistribution",
        "cloudfront:GetDistributionConfig",
        "cloudfront:GetFunction",
        "cloudfront:GetOriginAccessControl",
        "cloudfront:GetOriginRequestPolicy",
        "cloudfront:GetResponseHeadersPolicy",
        "cloudfront:ListTagsForResource",
        "cloudwatch:DescribeAlarms",
        "logs:DescribeLogGroups",
    }
    for statement in policy["Statement"]:
        actions = set(
            [statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"]
        )
        if statement["Resource"] == ["*"] and actions & {
            action for action in _actions(policy) if action.startswith(("events:", "logs:", "sns:"))
        }:
            assert actions <= allowed_global_reads

    serialized = json.dumps(policy)
    assert "/aws/sagemaker/TrainingJobs" not in serialized
    assert "/aws/sagemaker/ProcessingJobs" not in serialized
    assert f"/aws/*/{PROJECT}-prod-*" in serialized

    assert seed_role_name("dev") != seed_role_name("prod")
    assert f"/{PROJECT}/prod/terraform.tfstate" in compact


def test_state_policy_contains_exact_provider_reads_and_self_only_simulation() -> None:
    policy = build_state_policy(ACCOUNT_ID)
    bucket = _statement(policy, "FixedStateBucketContract")
    state = _statement(policy, "BootstrapStateObject")
    lock = _statement(policy, "BootstrapLockObject")
    ledger_read = _statement(policy, "ReadFinancialLedger")
    ledger_create = _statement(policy, "CreateFinancialLedgerWithCas")
    ledger_update = _statement(policy, "UpdateFinancialLedgerWithCas")
    simulation = _statement(policy, "SimulateOnlyThisBootstrapRole")
    audit = _statement(policy, "AuditOnlyThisBootstrapRole")

    assert set(bucket["Action"]) >= STATE_BUCKET_READ_ACTIONS
    assert bucket["Resource"] == [f"arn:aws:s3:::{PROJECT}-terraform-state-{ACCOUNT_ID}-us-east-1"]
    assert state["Action"] == ["s3:GetObject", "s3:PutObject"]
    assert state["Resource"] == [
        f"arn:aws:s3:::{PROJECT}-terraform-state-{ACCOUNT_ID}-us-east-1/"
        f"{PROJECT}/bootstrap/terraform.tfstate"
    ]
    assert lock["Action"] == ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
    assert lock["Resource"] == [f"{state['Resource'][0]}.tflock"]
    ledger_arn = (
        f"arn:aws:s3:::{PROJECT}-terraform-state-{ACCOUNT_ID}-us-east-1/cost-control/ledger.json"
    )
    assert ledger_read == {
        "Sid": "ReadFinancialLedger",
        "Effect": "Allow",
        "Action": ["s3:GetObject"],
        "Resource": [ledger_arn],
    }
    assert ledger_create["Condition"] == {"StringEquals": {"s3:if-none-match": "*"}}
    assert ledger_update["Condition"] == {"Null": {"s3:if-match": "false"}}
    assert ledger_create["Resource"] == ledger_update["Resource"] == [ledger_arn]
    assert simulation["Resource"] == [f"arn:aws:iam::{ACCOUNT_ID}:role/{STATE_ROLE_NAME}"]
    assert set(audit["Action"]) == {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
    }
    assert audit["Resource"] == simulation["Resource"]
    assert "s3:DeleteBucket" not in _actions(policy)


def test_seed_trust_uses_immutable_repository_identity_and_one_environment() -> None:
    trust = build_trust(ACCOUNT_ID, OWNER, OWNER_ID, REPOSITORY_ID)
    condition = trust["Statement"][0]["Condition"]["StringEquals"]

    assert condition == {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:ref": "refs/heads/main",
        "token.actions.githubusercontent.com:repository": (
            f"{OWNER}/machine-learning-product-search-ranking-platform"
        ),
        "token.actions.githubusercontent.com:repository_id": REPOSITORY_ID,
        "token.actions.githubusercontent.com:repository_owner_id": OWNER_ID,
        "token.actions.githubusercontent.com:sub": (
            f"repo:{OWNER}@{OWNER_ID}/machine-learning-product-search-ranking-platform"
            f"@{REPOSITORY_ID}:environment:aws-infrastructure:job_workflow_ref:"
            f"{OWNER}/machine-learning-product-search-ranking-platform/.github/workflows/"
            "infrastructure.yml@refs/heads/main"
        ),
    }

    state_trust = build_trust(ACCOUNT_ID, OWNER, OWNER_ID, REPOSITORY_ID, "state-bootstrap")
    state_subject = state_trust["Statement"][0]["Condition"]["StringEquals"][
        "token.actions.githubusercontent.com:sub"
    ]
    assert state_subject.endswith(
        ":environment:aws-state-bootstrap:job_workflow_ref:"
        f"{OWNER}/machine-learning-product-search-ranking-platform/.github/workflows/"
        "bootstrap-infrastructure.yml@refs/heads/main"
    )


def test_state_bootstrap_preflights_live_authority_before_fixed_six_resource_apply() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "bootstrap-infrastructure.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    bootstrap_hcl = (ROOT / "infra/terraform/environments/bootstrap/main.tf").read_text(
        encoding="utf-8"
    )

    assert workflow["on"]["workflow_dispatch"]["inputs"].keys() == {
        "operation",
        "owner_alias",
        "reviewed_commit_sha",
        "approved_plan_sha256",
        "authorization",
    }
    preflight = workflow_text.index("Prove the complete state-bootstrap authorization")
    apply = workflow_text.index("terraform apply -input=false -auto-approve")
    assert preflight < apply
    assert "aws iam simulate-principal-policy" in workflow_text[preflight:apply]
    assert "build_state_policy" in workflow_text[preflight:apply]
    assert "build_trust" in workflow_text[preflight:apply]
    assert 'PolicyNames") != ["fixed-six-resource-state-bootstrap"]' in workflow_text
    assert 'AttachedPolicies") != []' in workflow_text
    assert all(action in workflow_text[preflight:apply] for action in STATE_BUCKET_READ_ACTIONS)

    resources = re.findall(r'^resource "([^"]+)" "([^"]+)"', bootstrap_hcl, re.MULTILINE)
    assert set(resources) == {
        ("aws_s3_bucket", "state"),
        ("aws_s3_bucket_lifecycle_configuration", "state"),
        ("aws_s3_bucket_ownership_controls", "state"),
        ("aws_s3_bucket_public_access_block", "state"),
        ("aws_s3_bucket_server_side_encryption_configuration", "state"),
        ("aws_s3_bucket_versioning", "state"),
    }
    assert "if set(managed) != expected" in workflow_text
    assert 'actions != ["create"]' in workflow_text
    assert 'lockfile_sha256_before="$(sha256sum .terraform.lock.hcl' in workflow_text
    assert 'test "${lockfile_sha256_before}" = "${lockfile_sha256_after}"' in workflow_text
    assert '"reviewed_commit_sha": os.environ["TARGET_COMMIT"]' in workflow_text
    assert '"terraform_lock_sha256": os.environ["TF_LOCKFILE_SHA256"]' in workflow_text
    assert '"provider_selections": version.get("provider_selections", {})' in workflow_text


def test_platform_plan_digest_binds_reviewed_commit_and_locked_providers() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "infrastructure.yml"
    source = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]

    assert "reviewed_commit_sha" in inputs
    assert '[[ "${REVIEWED_COMMIT_SHA}" =~ ^[0-9a-f]{40}$ ]]' in source
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_COMMIT}"' in source
    assert 'git merge-base --is-ancestor "${TARGET_COMMIT}" "origin/main"' in source
    assert "terraform init -input=false \\" in source
    assert "            -lockfile=readonly" in source
    assert 'test "${lockfile_sha256_before}" = "${lockfile_sha256_after}"' in source
    assert '"reviewed_commit_sha": os.environ["TARGET_COMMIT"]' in source
    assert '"terraform_lock_sha256": os.environ["TF_LOCKFILE_SHA256"]' in source
    assert '"provider_selections": version.get("provider_selections", {})' in source
    assert '"deployment_identity_mode": os.environ["DEPLOYMENT_IDENTITY_MODE"]' in source
    assert '"boundary_policy_sha256": os.environ["BOUNDARY_POLICY_SHA256"]' in source
    assert 'test "${plan_hash}" = "${APPROVED_PLAN_SHA256}"' in source


def test_platform_workflow_attests_seed_and_boundary_before_any_plan() -> None:
    source = (ROOT / ".github/workflows/infrastructure.yml").read_text(encoding="utf-8")
    attestation = source.index("Attest the exact deployment identity and first-apply trust root")
    plan = source.index("terraform plan -input=false")

    assert attestation < plan
    assert "product-search-github-platform-seed-prod" in source[attestation:plan]
    assert "product-search-ranking-prod-permissions-boundary" in source[attestation:plan]
    assert "aws iam get-role-policy" in source[attestation:plan]
    assert "aws iam list-attached-role-policies" in source[attestation:plan]
    assert "aws iam get-policy-version" in source[attestation:plan]
    assert 'inline_names != ["first-platform-apply-only"]' in source[attestation:plan]
    assert 'build_platform_seed_policy(account_id, "prod")' in source[attestation:plan]
    assert 'build_boundary(account_id, "prod")' in source[attestation:plan]
    assert "persistent infrastructure role cannot change identities or bucket policies" in source


def test_platform_workflow_only_preserves_a_public_surface_already_present_in_state() -> None:
    source = (ROOT / ".github/workflows/infrastructure.yml").read_text(encoding="utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    state_detection = source.index("public_serving_enabled=false")
    plan = source.index("terraform plan -input=false")

    assert "enable_public_serving" not in inputs
    assert source.index("terraform state list") < plan
    assert state_detection < source.index("terraform state list")
    assert 'if [[ "${serving_enabled}" == "true" ]]' in source[state_detection:plan]
    assert "terraform show -json > current-state.private.json" in source[:state_detection]
    assert "SEARCH_RANK_SERVICE_VERSION" in source[:state_detection]
    assert "SEARCH_RANK_DEPLOYMENT_NONCE" in source[:state_detection]
    assert '-var="serving_git_sha=${serving_git_sha}"' in source
    assert '-var="serving_deployment_nonce=${serving_deployment_nonce}"' in source
    assert "module.platform.aws_apigatewayv2_api.production[0]" in source[state_detection:plan]
    assert "module.platform.aws_cloudfront_distribution.site[0]" in source[state_detection:plan]
    assert "public_serving_enabled=true" in source[state_detection:plan]
    assert '-var="enable_public_serving=${public_serving_enabled}"' in source[plan:]


def test_alert_addresses_are_secrets_with_only_presence_declassified() -> None:
    workflow = (ROOT / ".github/workflows/infrastructure.yml").read_text(encoding="utf-8")
    locals_hcl = (ROOT / "infra/terraform/modules/platform/locals.tf").read_text(encoding="utf-8")
    observability = (ROOT / "infra/terraform/modules/platform/observability.tf").read_text(
        encoding="utf-8"
    )

    assert "TF_BUDGET_NOTIFICATION_EMAIL: ${{ secrets.AWS_BUDGET_NOTIFICATION_EMAIL }}" in workflow
    assert "TF_ALARM_NOTIFICATION_EMAIL: ${{ secrets.AWS_ALARM_NOTIFICATION_EMAIL }}" in workflow
    assert "vars.AWS_BUDGET_NOTIFICATION_EMAIL" not in workflow
    assert "vars.AWS_ALARM_NOTIFICATION_EMAIL" not in workflow
    assert 'nonsensitive(var.alarm_notification_email != "")' in locals_hcl
    assert "count = local.alarm_notifications_enabled ? 1 : 0" in observability
    assert "endpoint  = var.alarm_notification_email" in observability


def test_infrastructure_and_production_roles_have_separate_non_escalating_authority() -> None:
    iam = (ROOT / "infra/terraform/modules/platform/iam.tf").read_text(encoding="utf-8")
    infrastructure = iam.split('data "aws_iam_policy_document" "github_terraform" {', 1)[1].split(
        'resource "aws_iam_role_policy" "github_terraform" {', 1
    )[0]
    production = iam.split('data "aws_iam_policy_document" "github_production_terraform" {', 1)[
        1
    ].split('data "aws_iam_policy_document" "github_production" {', 1)[0]
    deployment = iam.split('data "aws_iam_policy_document" "github_deployment" {', 1)[1].split(
        'data "aws_iam_policy_document" "github_images" {', 1
    )[0]

    for block in (infrastructure, production):
        assert '${var.project_name}/prod/terraform.tfstate"' in block
        assert '${var.project_name}/prod/terraform.tfstate.tflock"' in block
        assert 'actions   = ["s3:GetObject", "s3:PutObject"]' in block
        assert 'actions   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]' in block

    assert 'role   = aws_iam_role.github_workflow["aws-infrastructure"].id' in iam
    assert "policy = data.aws_iam_policy_document.github_terraform.minified_json" in iam
    assert "length(data.aws_iam_policy_document.github_terraform.minified_json) <= 10240" in iam
    assert "policy = data.aws_iam_policy_document.github_production.minified_json" in iam
    assert "length(data.aws_iam_policy_document.github_production.minified_json) <= 10240" in iam

    forbidden_identity_actions = {
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:DeleteRolePermissionsBoundary",
        "iam:DeleteRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:PutRolePolicy",
        "iam:UpdateAssumeRolePolicy",
    }
    assert forbidden_identity_actions.isdisjoint(re.findall(r'"(iam:[A-Za-z]+)"', infrastructure))
    assert forbidden_identity_actions.isdisjoint(re.findall(r'"(iam:[A-Za-z]+)"', production))
    assert "s3:PutBucketPolicy" not in infrastructure
    assert "s3:DeleteBucketPolicy" not in infrastructure
    site_policy = next(
        block
        for block in production.split("statement {")
        if 'actions   = ["s3:PutBucketPolicy"]' in block
    )
    assert 'actions   = ["s3:PutBucketPolicy"]' in site_policy
    assert "resources = [local.site_bucket_arn]" in site_policy
    assert "local.artifact_bucket_arn" not in site_policy
    assert 'actions = ["iam:PassRole"]' in deployment
    assert "local.lambda_role_arn" in deployment
    assert 'actions   = ["apigateway:POST"]' in production
    assert (
        'actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction", "cloudfront:TagResource"]'
        in production
    )
    assert 'variable = "aws:RequestTag/Project"' in production
    for action in (
        "lambda:AddPermission",
        "lambda:CreateAlias",
        "lambda:CreateFunction",
        "lambda:TagResource",
        "lambda:UntagResource",
    ):
        assert f'"{action}"' in production
    assert '"lambda:RemovePermission"' not in production
    for destructive in (
        "s3:DeleteBucket",
        "ecr:DeleteRepository",
        "lambda:DeleteFunction",
        "cloudwatch:DeleteAlarms",
        "events:DeleteRule",
        "logs:DeleteLogGroup",
        "sns:DeleteTopic",
        "budgets:DeleteBudget",
    ):
        assert f'"{destructive}"' not in infrastructure

    versioned = deployment.split('sid    = "VersionedLambdaRelease"', 1)[1].split("statement {", 1)[
        0
    ]
    assert '"lambda:PutFunctionConcurrency"' in versioned
    assert "local.artifact_bucket_arn" not in site_policy

    role_blocks = re.findall(r'resource "aws_iam_role" "[^"]+" \{(.*?)\n\}', iam, re.DOTALL)
    assert len(role_blocks) == 5
    assert all(
        "permissions_boundary = local.project_permissions_boundary_arn" in block
        for block in role_blocks
    )


def test_heldout_release_role_can_read_only_the_required_live_quota() -> None:
    iam = (ROOT / "infra/terraform/modules/platform/iam.tf").read_text(encoding="utf-8")
    heldout = iam.split('data "aws_iam_policy_document" "github_heldout_release" {', 1)[1].split(
        'resource "aws_iam_role_policy" "github_heldout_release" {', 1
    )[0]
    quota = heldout.split('sid       = "ReadProcessingJobQuota"', 1)[1].split("statement {", 1)[0]

    assert 'actions   = ["servicequotas:GetServiceQuota"]' in quota
    assert 'resources = ["*"]' in quota
    assert heldout.count('"servicequotas:GetServiceQuota"') == 1


def test_cloudfront_function_is_tagged_for_request_and_resource_tag_guards() -> None:
    serving = (ROOT / "infra/terraform/modules/platform/serving.tf").read_text(encoding="utf-8")
    function = serving.split('resource "aws_cloudfront_function" "spa_rewrite" {', 1)[1].split(
        "}\n", 1
    )[0]

    assert "tags    = local.common_tags" in function
