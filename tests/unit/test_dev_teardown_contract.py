from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest

from scripts.dev_teardown_contract import (
    PROOF_RESOURCE_ADDRESSES,
    RESIDUAL_FIELDS,
    DevTeardownContractError,
    build_plan_contract,
    build_verified_evidence,
    canonical_sha256,
    count_managed_state_resources,
)

ACCOUNT_ID = "123456789012"
SOURCE_SHA = "a" * 40
LOCK_SHA = "b" * 64
STATE_SHA = "c" * 64
PREFIX = "product-search-ranking-dev"


def _index(address: str) -> str | None:
    match = re.search(r'\["([^"]+)"\]$', address)
    return match.group(1) if match else None


def _role_name(address: str) -> str:
    index = _index(address)
    if ".github_workflow[" in address:
        assert index is not None
        return f"{PREFIX}-github-{index}"
    suffix = address.rsplit(".", 1)[-1]
    return {
        "github_deployment": f"{PREFIX}-github-production",
        "lambda": f"{PREFIX}-lambda",
        "sagemaker_processing": f"{PREFIX}-sagemaker-processing",
        "sagemaker_training": f"{PREFIX}-sagemaker-training",
    }[suffix]


def _policy_role(address: str) -> str:
    index = _index(address)
    if ".github_financial_ledger[" in address:
        assert index is not None
        return f"{PREFIX}-github-{index}"
    suffix = address.rsplit(".", 1)[-1]
    github_roles = {
        "github_baseline": "aws-baseline",
        "github_baseline_release": "baseline-release",
        "github_benchmark": "production-benchmark",
        "github_data": "aws-data",
        "github_deployment": "production",
        "github_heldout_release": "heldout-release",
        "github_images": "aws-images",
        "github_terraform": "aws-infrastructure",
        "github_training": "aws-training",
        "github_trial_selection": "aws-trial-selection",
    }
    if suffix in github_roles:
        return f"{PREFIX}-github-{github_roles[suffix]}"
    return {
        "lambda": f"{PREFIX}-lambda",
        "sagemaker_processing": f"{PREFIX}-sagemaker-processing",
        "sagemaker_training": f"{PREFIX}-sagemaker-training",
    }[suffix]


def _before(address: str, resource_type: str) -> dict[str, Any]:
    tags = {"Environment": "dev", "Project": "product-search-ranking"}
    suffix = address.rsplit(".", 1)[-1]
    bucket = (
        f"{PREFIX}-{ACCOUNT_ID}-us-east-1-artifacts"
        if suffix == "artifacts"
        else f"{PREFIX}-{ACCOUNT_ID}-us-east-1-site"
    )
    index = _index(address)
    if resource_type == "aws_s3_bucket":
        return {"bucket": bucket, "tags": tags}
    if resource_type.startswith("aws_s3_bucket_"):
        return {"bucket": bucket}
    if resource_type == "aws_ecr_repository":
        assert index is not None
        return {"name": f"{PREFIX}-{index}", "tags": tags}
    if resource_type in {"aws_ecr_lifecycle_policy", "aws_ecr_repository_policy"}:
        kind = index or "serve"
        return {"repository": f"{PREFIX}-{kind}"}
    if resource_type == "aws_iam_role":
        return {"name": _role_name(address), "tags": tags}
    if resource_type == "aws_iam_role_policy":
        return {"role": _policy_role(address)}
    if resource_type == "aws_cloudwatch_log_group":
        names = {
            "candidate_api": f"/aws/apigateway/{PREFIX}-candidate",
            "lambda": f"/aws/lambda/{PREFIX}-api",
            "production_api": f"/aws/apigateway/{PREFIX}-production",
        }
        return {"name": names[suffix], "tags": tags}
    raise AssertionError(resource_type)


def valid_plan() -> dict[str, Any]:
    changes = []
    for address in sorted(PROOF_RESOURCE_ADDRESSES):
        resource_type = address.split("module.platform.", 1)[1].split(".", 1)[0]
        changes.append(
            {
                "address": address,
                "mode": "managed",
                "provider_name": "registry.terraform.io/hashicorp/aws",
                "type": resource_type,
                "change": {
                    "actions": ["delete"],
                    "after": None,
                    "before": _before(address, resource_type),
                },
            }
        )
    return {
        "applyable": True,
        "complete": True,
        "deferred_changes": [],
        "errored": False,
        "resource_changes": changes,
        "resource_drift": [],
        "terraform_version": "1.10.5",
    }


def _build(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_plan_contract(
        plan or valid_plan(),
        account_id=ACCOUNT_ID,
        source_sha=SOURCE_SHA,
        terraform_lock_sha256=LOCK_SHA,
        state_sha256=STATE_SHA,
    )


def test_plan_contract_is_exact_value_free_and_deterministic() -> None:
    plan_with_read = valid_plan()
    plan_with_read["resource_changes"].append(
        {
            "address": "module.platform.data.aws_caller_identity.current",
            "mode": "data",
            "provider_name": "registry.terraform.io/hashicorp/aws",
            "type": "aws_caller_identity",
            "change": {"actions": ["read"], "after": {}, "before": None},
        }
    )
    first = _build(plan_with_read)
    second = _build(copy.deepcopy(valid_plan()))

    assert first == second
    assert first["resource_count"] == 56
    assert canonical_sha256(first) == canonical_sha256(second)
    serialized = json.dumps(first, sort_keys=True)
    assert ACCOUNT_ID not in serialized
    assert "arn:aws" not in serialized
    assert f"{PREFIX}-{ACCOUNT_ID}-us-east-1-artifacts" not in serialized
    assert f"{PREFIX}-{ACCOUNT_ID}-us-east-1-site" not in serialized
    assert f"{PREFIX}-" not in serialized


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda plan: plan["resource_changes"].pop(),
            "exact non-serving dev fixture",
        ),
        (
            lambda plan: plan["resource_changes"][0]["change"].update(
                {"actions": ["create", "delete"]}
            ),
            "delete-only",
        ),
        (
            lambda plan: plan.update({"resource_drift": [{"address": "unexpected"}]}),
            "resource drift",
        ),
    ],
)
def test_plan_contract_rejects_scope_or_state_changes(mutate: Any, message: str) -> None:
    plan = valid_plan()
    mutate(plan)
    with pytest.raises(DevTeardownContractError, match=message):
        _build(plan)


def test_plan_contract_rejects_a_bucket_from_another_account() -> None:
    plan = valid_plan()
    bucket = next(item for item in plan["resource_changes"] if item["type"] == "aws_s3_bucket")
    bucket["change"]["before"]["bucket"] = "product-search-ranking-dev-999999999999-us-east-1-site"

    with pytest.raises(DevTeardownContractError, match="exact dev bucket"):
        _build(plan)


def test_plan_contract_rejects_a_mutating_data_source_record() -> None:
    plan = valid_plan()
    plan["resource_changes"].append(
        {
            "address": "module.platform.data.aws_caller_identity.current",
            "mode": "data",
            "provider_name": "registry.terraform.io/hashicorp/aws",
            "type": "aws_caller_identity",
            "change": {"actions": ["delete"], "after": None, "before": {}},
        }
    )

    with pytest.raises(DevTeardownContractError, match="read-only data-source"):
        _build(plan)


def test_verified_evidence_remains_truthful_until_external_role_cleanup() -> None:
    contract = _build()
    absence = {
        "residual_counts": {field: 0 for field in RESIDUAL_FIELDS},
        "state_backend_retained": True,
    }
    evidence = build_verified_evidence(
        contract,
        absence,
        completed_at="2026-09-18T21:00:00Z",
        operator_alias="portfolio-owner",
    )

    assert evidence["status"] == "dev_resources_destroyed_external_role_cleanup_pending"
    assert evidence["fr_cloud_009_complete"] is False
    assert evidence["external_lifecycle_role_cleanup_required"] is True
    assert evidence["shared_oidc_provider_disposition"] == "retained_account_shared"
    assert evidence["plan_sha256"] == canonical_sha256(contract)


def test_verified_evidence_rejects_any_residual() -> None:
    absence = {
        "residual_counts": {field: 0 for field in RESIDUAL_FIELDS},
        "state_backend_retained": True,
    }
    absence["residual_counts"]["s3_buckets"] = 1

    with pytest.raises(DevTeardownContractError, match="residual resources"):
        build_verified_evidence(
            _build(),
            absence,
            completed_at="2026-09-18T21:00:00Z",
            operator_alias="portfolio-owner",
        )


def test_state_count_ignores_read_only_data_sources() -> None:
    state = {
        "values": {
            "root_module": {
                "resources": [{"mode": "data"}],
                "child_modules": [
                    {
                        "resources": [
                            {"mode": "managed"},
                            {"mode": "data"},
                        ]
                    }
                ],
            }
        }
    }

    assert count_managed_state_resources(state) == 1
    assert count_managed_state_resources({}) == 0
