"""Validate and sanitize the disposable-dev Terraform teardown contract.

The reviewed fingerprint intentionally contains no AWS account number, ARN, bucket name, object
key, email, or Terraform values. Private plan/state material is consumed only to prove that the
exact, non-serving dev fixture is being destroyed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = "product-search-ranking"
ENVIRONMENT = "dev"
REGION = "us-east-1"
SCHEMA_VERSION = "1.0.0"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")

PROOF_RESOURCE_ADDRESSES = frozenset(
    {
        "module.platform.aws_cloudwatch_log_group.candidate_api",
        "module.platform.aws_cloudwatch_log_group.lambda",
        "module.platform.aws_cloudwatch_log_group.production_api",
        "module.platform.aws_ecr_lifecycle_policy.serve",
        'module.platform.aws_ecr_lifecycle_policy.train_eval["eval"]',
        'module.platform.aws_ecr_lifecycle_policy.train_eval["train"]',
        'module.platform.aws_ecr_repository.images["eval"]',
        'module.platform.aws_ecr_repository.images["serve"]',
        'module.platform.aws_ecr_repository.images["train"]',
        "module.platform.aws_ecr_repository_policy.serve",
        "module.platform.aws_iam_role.github_deployment",
        'module.platform.aws_iam_role.github_workflow["aws-baseline"]',
        'module.platform.aws_iam_role.github_workflow["aws-data"]',
        'module.platform.aws_iam_role.github_workflow["aws-images"]',
        'module.platform.aws_iam_role.github_workflow["aws-infrastructure"]',
        'module.platform.aws_iam_role.github_workflow["aws-training"]',
        'module.platform.aws_iam_role.github_workflow["aws-trial-selection"]',
        'module.platform.aws_iam_role.github_workflow["baseline-release"]',
        'module.platform.aws_iam_role.github_workflow["heldout-release"]',
        'module.platform.aws_iam_role.github_workflow["production-benchmark"]',
        "module.platform.aws_iam_role.lambda",
        "module.platform.aws_iam_role.sagemaker_processing",
        "module.platform.aws_iam_role.sagemaker_training",
        "module.platform.aws_iam_role_policy.github_baseline",
        "module.platform.aws_iam_role_policy.github_baseline_release",
        "module.platform.aws_iam_role_policy.github_benchmark",
        "module.platform.aws_iam_role_policy.github_data",
        "module.platform.aws_iam_role_policy.github_deployment",
        'module.platform.aws_iam_role_policy.github_financial_ledger["aws-baseline"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["aws-data"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["aws-images"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["aws-training"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["aws-trial-selection"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["baseline-release"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["heldout-release"]',
        'module.platform.aws_iam_role_policy.github_financial_ledger["production-benchmark"]',
        "module.platform.aws_iam_role_policy.github_heldout_release",
        "module.platform.aws_iam_role_policy.github_images",
        "module.platform.aws_iam_role_policy.github_terraform",
        "module.platform.aws_iam_role_policy.github_training",
        "module.platform.aws_iam_role_policy.github_trial_selection",
        "module.platform.aws_iam_role_policy.lambda",
        "module.platform.aws_iam_role_policy.sagemaker_processing",
        "module.platform.aws_iam_role_policy.sagemaker_training",
        "module.platform.aws_s3_bucket.artifacts",
        "module.platform.aws_s3_bucket.site",
        "module.platform.aws_s3_bucket_lifecycle_configuration.artifacts",
        "module.platform.aws_s3_bucket_lifecycle_configuration.site",
        "module.platform.aws_s3_bucket_ownership_controls.artifacts",
        "module.platform.aws_s3_bucket_ownership_controls.site",
        "module.platform.aws_s3_bucket_public_access_block.artifacts",
        "module.platform.aws_s3_bucket_public_access_block.site",
        "module.platform.aws_s3_bucket_server_side_encryption_configuration.artifacts",
        "module.platform.aws_s3_bucket_server_side_encryption_configuration.site",
        "module.platform.aws_s3_bucket_versioning.artifacts",
        "module.platform.aws_s3_bucket_versioning.site",
    }
)

RESIDUAL_FIELDS = frozenset(
    {
        "active_processing_jobs",
        "active_training_jobs",
        "api_gateways",
        "budgets",
        "cloudfront_distributions",
        "cloudfront_functions",
        "cloudfront_origin_access_controls",
        "cloudfront_response_headers_policies",
        "ecr_repositories",
        "event_rules",
        "iam_roles",
        "lambda_functions",
        "log_groups",
        "s3_buckets",
        "sns_topics",
        "terraform_state_resources",
    }
)


class DevTeardownContractError(ValueError):
    """The private plan or sanitized proof does not match the dev teardown contract."""


def _require_sha(value: str, *, git: bool, label: str) -> str:
    pattern = GIT_SHA_RE if git else SHA256_RE
    if pattern.fullmatch(value) is None:
        raise DevTeardownContractError(f"{label} is not an exact lowercase digest")
    return value


def expected_resource_names(account_id: str) -> tuple[set[str], set[str], set[str], set[str]]:
    prefix = f"{PROJECT}-{ENVIRONMENT}"
    buckets = {
        f"{prefix}-{account_id}-{REGION}-artifacts",
        f"{prefix}-{account_id}-{REGION}-site",
    }
    repositories = {f"{prefix}-{kind}" for kind in ("eval", "serve", "train")}
    roles = {
        f"{prefix}-sagemaker-training",
        f"{prefix}-sagemaker-processing",
        f"{prefix}-lambda",
        f"{prefix}-budget-kill-switch",
        f"{prefix}-github-production",
        f"{prefix}-github-aws-baseline",
        f"{prefix}-github-aws-data",
        f"{prefix}-github-aws-images",
        f"{prefix}-github-aws-infrastructure",
        f"{prefix}-github-aws-training",
        f"{prefix}-github-aws-trial-selection",
        f"{prefix}-github-baseline-release",
        f"{prefix}-github-heldout-release",
        f"{prefix}-github-production-benchmark",
    }
    log_groups = {
        f"/aws/apigateway/{prefix}-candidate",
        f"/aws/apigateway/{prefix}-production",
        f"/aws/lambda/{prefix}-api",
    }
    return buckets, repositories, roles, log_groups


def _validate_tags(values: dict[str, Any], address: str) -> None:
    tags = values.get("tags")
    if tags is None:
        tags = values.get("tags_all")
    if not isinstance(tags, dict):
        raise DevTeardownContractError(f"{address} lacks concrete dev ownership tags")
    if tags.get("Project") != PROJECT or tags.get("Environment") != ENVIRONMENT:
        raise DevTeardownContractError(f"{address} is not tagged for the disposable dev scope")


def _validate_private_values(change: dict[str, Any], account_id: str) -> None:
    address = change["address"]
    resource_type = change.get("type")
    body = change.get("change")
    if not isinstance(body, dict) or not isinstance(body.get("before"), dict):
        raise DevTeardownContractError(f"{address} lacks concrete prior values")
    values: dict[str, Any] = body["before"]
    buckets, repositories, roles, log_groups = expected_resource_names(account_id)

    if resource_type == "aws_s3_bucket":
        if values.get("bucket") not in buckets:
            raise DevTeardownContractError(f"{address} is not an exact dev bucket")
        _validate_tags(values, address)
    elif resource_type.startswith("aws_s3_bucket_"):
        if values.get("bucket") not in buckets:
            raise DevTeardownContractError(f"{address} references a bucket outside dev")
    elif resource_type == "aws_ecr_repository":
        if values.get("name") not in repositories:
            raise DevTeardownContractError(f"{address} is not an exact dev repository")
        _validate_tags(values, address)
    elif resource_type in {"aws_ecr_lifecycle_policy", "aws_ecr_repository_policy"}:
        if values.get("repository") not in repositories:
            raise DevTeardownContractError(f"{address} references a repository outside dev")
    elif resource_type == "aws_iam_role":
        if values.get("name") not in roles:
            raise DevTeardownContractError(f"{address} is not an exact Terraform-managed dev role")
        _validate_tags(values, address)
    elif resource_type == "aws_iam_role_policy":
        role = values.get("role")
        if not isinstance(role, str) or role not in roles:
            raise DevTeardownContractError(f"{address} references an IAM role outside dev")
    elif resource_type == "aws_cloudwatch_log_group":
        if values.get("name") not in log_groups:
            raise DevTeardownContractError(f"{address} is not an exact base dev log group")
        _validate_tags(values, address)
    else:
        raise DevTeardownContractError(f"{address} uses a resource type outside the proof profile")


def build_plan_contract(
    plan: dict[str, Any],
    *,
    account_id: str,
    source_sha: str,
    terraform_lock_sha256: str,
    state_sha256: str,
) -> dict[str, Any]:
    """Validate a private destroy plan and return its value-free public contract."""

    if ACCOUNT_RE.fullmatch(account_id) is None:
        raise DevTeardownContractError("account_id must be exactly 12 decimal digits")
    _require_sha(source_sha, git=True, label="source_sha")
    _require_sha(terraform_lock_sha256, git=False, label="terraform_lock_sha256")
    _require_sha(state_sha256, git=False, label="state_sha256")
    if plan.get("errored") is not False or plan.get("applyable") is not True:
        raise DevTeardownContractError("Terraform destroy plan is not applyable")
    if plan.get("complete") is not True:
        raise DevTeardownContractError("Terraform destroy plan is incomplete")
    if plan.get("resource_drift") not in (None, []):
        raise DevTeardownContractError("Terraform state has unreviewed resource drift")
    if plan.get("deferred_changes") not in (None, []):
        raise DevTeardownContractError("Terraform destroy plan contains deferred changes")

    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise DevTeardownContractError("Terraform plan resource_changes must be a list")
    by_address: dict[str, dict[str, Any]] = {}
    sanitized_resources: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            raise DevTeardownContractError("Terraform resource change entries must be objects")
        address = change.get("address")
        if not isinstance(address, str) or address in by_address:
            raise DevTeardownContractError("Terraform resource addresses must be unique strings")
        body = change.get("change")
        if not isinstance(body, dict):
            raise DevTeardownContractError(f"{address} lacks a Terraform change body")
        if change.get("mode") == "data":
            if (
                not address.startswith("module.platform.data.")
                or body.get("actions") not in (["no-op"], ["read"])
                or change.get("provider_name")
                not in {
                    "registry.terraform.io/hashicorp/aws",
                    "registry.terraform.io/hashicorp/tls",
                }
            ):
                raise DevTeardownContractError(f"{address} is not a read-only data-source refresh")
            by_address[address] = change
            continue
        if change.get("mode") != "managed":
            raise DevTeardownContractError(f"{address} has an unsupported Terraform mode")
        if body.get("actions") != ["delete"]:
            raise DevTeardownContractError(f"{address} is not an exact delete-only action")
        if body.get("after") is not None:
            raise DevTeardownContractError(
                f"{address} destroy action unexpectedly has after values"
            )
        if change.get("provider_name") != "registry.terraform.io/hashicorp/aws":
            raise DevTeardownContractError(f"{address} is not managed by the locked AWS provider")
        _validate_private_values(change, account_id)
        by_address[address] = change
        sanitized_resources.append(
            {
                "actions": ["delete"],
                "address": address,
                "type": change.get("type"),
            }
        )

    actual = {address for address, change in by_address.items() if change.get("mode") == "managed"}
    if actual != PROOF_RESOURCE_ADDRESSES:
        missing = len(PROOF_RESOURCE_ADDRESSES - actual)
        unexpected = len(actual - PROOF_RESOURCE_ADDRESSES)
        raise DevTeardownContractError(
            "Destroy plan differs from the exact non-serving dev fixture "
            f"(missing={missing}, unexpected={unexpected})"
        )

    terraform_version = plan.get("terraform_version")
    if not isinstance(terraform_version, str) or not terraform_version:
        raise DevTeardownContractError("Terraform plan lacks its tool version")
    return {
        "environment": ENVIRONMENT,
        "plan_flags": {"applyable": True, "complete": True, "errored": False},
        "proof_profile": "base-infrastructure-no-serving-no-budgets",
        "region": REGION,
        "resource_count": len(sanitized_resources),
        "resources": sorted(sanitized_resources, key=lambda item: item["address"]),
        "schema_version": SCHEMA_VERSION,
        "source_commit_sha": source_sha,
        "state_sha256": state_sha256,
        "terraform_lock_sha256": terraform_lock_sha256,
        "terraform_version": terraform_version,
    }


def canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def count_managed_state_resources(state: dict[str, Any]) -> int:
    """Count only managed resources without emitting private Terraform state values."""

    def count_module(module: object) -> int:
        if not isinstance(module, dict):
            raise DevTeardownContractError("Terraform state module must be an object")
        resources = module.get("resources", [])
        children = module.get("child_modules", [])
        if not isinstance(resources, list) or not isinstance(children, list):
            raise DevTeardownContractError("Terraform state has an invalid module shape")
        count = 0
        for resource in resources:
            if not isinstance(resource, dict) or resource.get("mode") not in {"data", "managed"}:
                raise DevTeardownContractError("Terraform state has an invalid resource envelope")
            count += int(resource["mode"] == "managed")
        return count + sum(count_module(child) for child in children)

    values = state.get("values")
    if values is None:
        return 0
    if not isinstance(values, dict):
        raise DevTeardownContractError("Terraform state values must be an object")
    root = values.get("root_module")
    if root is None:
        return 0
    return count_module(root)


def build_verified_evidence(
    plan_contract: dict[str, Any],
    absence: dict[str, Any],
    *,
    completed_at: str,
    operator_alias: str,
) -> dict[str, Any]:
    """Create public evidence only after every disposable-dev absence check is zero."""

    try:
        parsed_completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise DevTeardownContractError("completed_at must be an ISO-8601 timestamp") from error
    if parsed_completed_at.tzinfo is None:
        raise DevTeardownContractError("completed_at must include a timezone")
    if ALIAS_RE.fullmatch(operator_alias) is None:
        raise DevTeardownContractError("operator_alias must be a non-sensitive project alias")
    if plan_contract.get("schema_version") != SCHEMA_VERSION:
        raise DevTeardownContractError("plan contract schema is unsupported")
    if plan_contract.get("environment") != ENVIRONMENT or plan_contract.get("region") != REGION:
        raise DevTeardownContractError("plan contract is not the fixed dev/us-east-1 scope")
    plan_sha = canonical_sha256(plan_contract)

    residuals = absence.get("residual_counts")
    if not isinstance(residuals, dict) or set(residuals) != RESIDUAL_FIELDS:
        raise DevTeardownContractError("absence result does not cover the exact residual inventory")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value != 0
        for value in residuals.values()
    ):
        raise DevTeardownContractError("disposable dev still has residual resources")
    if absence.get("state_backend_retained") is not True:
        raise DevTeardownContractError("protected bootstrap state retention was not proven")

    return {
        "authorization": {
            "exact_plan_fingerprint_matched": True,
            "external_role_attested": True,
            "protected_environment_approved": True,
        },
        "completed_at": completed_at,
        "environment": ENVIRONMENT,
        "external_lifecycle_role_cleanup_required": True,
        "fr_cloud_009_complete": False,
        "operator_alias": operator_alias,
        "plan_sha256": plan_sha,
        "proof_profile": plan_contract["proof_profile"],
        "region": REGION,
        "residual_counts": dict(sorted(residuals.items())),
        "schema_version": SCHEMA_VERSION,
        "source_commit_sha": plan_contract["source_commit_sha"],
        "state_backend_retained": True,
        "status": "dev_resources_destroyed_external_role_cleanup_pending",
    }


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DevTeardownContractError(f"{path.name} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _plan_command(args: argparse.Namespace) -> int:
    contract = build_plan_contract(
        _load_object(args.plan),
        account_id=args.account_id,
        source_sha=args.source_sha,
        terraform_lock_sha256=args.terraform_lock_sha256,
        state_sha256=args.state_sha256,
    )
    _write_json(args.output, contract)
    args.sha_output.write_text(canonical_sha256(contract) + "\n", encoding="utf-8")
    return 0


def _evidence_command(args: argparse.Namespace) -> int:
    evidence = build_verified_evidence(
        _load_object(args.plan_contract),
        _load_object(args.absence),
        completed_at=args.completed_at,
        operator_alias=args.operator_alias,
    )
    _write_json(args.output, evidence)
    return 0


def _state_count_command(args: argparse.Namespace) -> int:
    print(count_managed_state_resources(_load_object(args.state)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="validate a private destroy plan")
    plan.add_argument("--plan", required=True, type=Path)
    plan.add_argument("--account-id", required=True)
    plan.add_argument("--source-sha", required=True)
    plan.add_argument("--terraform-lock-sha256", required=True)
    plan.add_argument("--state-sha256", required=True)
    plan.add_argument("--output", required=True, type=Path)
    plan.add_argument("--sha-output", required=True, type=Path)
    plan.set_defaults(handler=_plan_command)

    evidence = subparsers.add_parser("evidence", help="emit sanitized post-destroy evidence")
    evidence.add_argument("--plan-contract", required=True, type=Path)
    evidence.add_argument("--absence", required=True, type=Path)
    evidence.add_argument("--completed-at", required=True)
    evidence.add_argument("--operator-alias", required=True)
    evidence.add_argument("--output", required=True, type=Path)
    evidence.set_defaults(handler=_evidence_command)

    state_count = subparsers.add_parser(
        "state-count", help="print only the managed-resource count from private state"
    )
    state_count.add_argument("--state", required=True, type=Path)
    state_count.set_defaults(handler=_state_count_command)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
