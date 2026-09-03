from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from scripts.canonicalize_terraform_plan import (
    CALLER_IDENTITY_ADDRESS,
    VOLATILE_STS_SESSION_SENTINEL,
    TerraformPlanNormalizationError,
    canonicalize_terraform_plan,
    normalize_volatile_caller_identity,
)


def _caller(
    *,
    session: str,
    account_id: str = "123456789012",
    role_name: str = "product-search-github-platform-seed-prod",
    role_id: str = "AROATESTROLEID",
) -> dict[str, Any]:
    return {
        "address": CALLER_IDENTITY_ADDRESS,
        "mode": "data",
        "type": "aws_caller_identity",
        "name": "current",
        "values": {
            "account_id": account_id,
            "arn": f"arn:aws:sts::{account_id}:assumed-role/{role_name}/{session}",
            "id": account_id,
            "user_id": f"{role_id}:{session}",
        },
    }


def _plan(
    *,
    session: str,
    account_id: str = "123456789012",
    role_name: str = "product-search-github-platform-seed-prod",
    role_id: str = "AROATESTROLEID",
    nested_id: str = "stable-nested-id",
) -> dict[str, Any]:
    caller = _caller(
        session=session,
        account_id=account_id,
        role_name=role_name,
        role_id=role_id,
    )
    managed = {
        "address": "module.platform.aws_s3_bucket.artifacts",
        "mode": "managed",
        "type": "aws_s3_bucket",
        "name": "artifacts",
        "values": {
            "nested_application_value": {
                "address": CALLER_IDENTITY_ADDRESS,
                "mode": "data",
                "type": "aws_caller_identity",
                "name": "current",
                "arn": "application-arn",
                "id": nested_id,
                "user_id": "application-user",
            }
        },
    }
    return {
        "format_version": "1.2",
        "timestamp": f"2026-09-03T03:00:00Z-{session}",
        "planned_values": {
            "root_module": {
                "child_modules": [
                    {
                        "address": "module.platform",
                        "resources": [caller, managed],
                    }
                ]
            }
        },
        "resource_changes": [
            {
                "address": CALLER_IDENTITY_ADDRESS,
                "mode": "data",
                "type": "aws_caller_identity",
                "name": "current",
                "change": {
                    "actions": ["read"],
                    "after": copy.deepcopy(caller["values"]),
                },
            }
        ],
    }


def _workflow_digest(payload: dict[str, Any]) -> str:
    normalized = canonicalize_terraform_plan(payload)
    normalized.pop("timestamp", None)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def test_only_sts_session_and_plan_timestamp_are_digest_invariant() -> None:
    assert _workflow_digest(_plan(session="plan-run")) == _workflow_digest(
        _plan(session="apply-run")
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "210987654321"),
        ("role_name", "product-search-ranking-prod-github-aws-infrastructure"),
        ("role_id", "AROADIFFERENTROLE"),
        ("nested_id", "changed-managed-resource-value"),
    ],
)
def test_stable_identity_and_managed_resource_changes_remain_hash_bound(
    field: str,
    value: str,
) -> None:
    assert _workflow_digest(_plan(session="plan")) != _workflow_digest(
        _plan(session="apply", **{field: value})
    )


def test_normalization_preserves_role_and_does_not_descend_into_managed_values() -> None:
    payload = _plan(session="volatile")
    normalized = normalize_volatile_caller_identity(payload)
    resources = normalized["planned_values"]["root_module"]["child_modules"][0]["resources"]
    caller, managed = resources

    assert caller["values"] == {
        "account_id": "123456789012",
        "arn": (
            "arn:aws:sts::123456789012:assumed-role/"
            f"product-search-github-platform-seed-prod/{VOLATILE_STS_SESSION_SENTINEL}"
        ),
        "id": "123456789012",
        "user_id": f"AROATESTROLEID:{VOLATILE_STS_SESSION_SENTINEL}",
    }
    assert managed == payload["planned_values"]["root_module"]["child_modules"][0]["resources"][1]
    assert payload["resource_changes"][0]["change"]["after"]["user_id"].endswith(":volatile")


def test_unexpected_caller_resource_envelope_fails_closed() -> None:
    payload = _plan(session="one")
    caller = payload["planned_values"]["root_module"]["child_modules"][0]["resources"][0]
    caller["mode"] = "managed"

    with pytest.raises(
        TerraformPlanNormalizationError,
        match="unexpected resource envelope",
    ):
        normalize_volatile_caller_identity(payload)


def test_non_assumed_role_caller_fails_closed() -> None:
    payload = _plan(session="one")
    caller = payload["planned_values"]["root_module"]["child_modules"][0]["resources"][0]
    caller["values"]["arn"] = "arn:aws:iam::123456789012:root"

    with pytest.raises(
        TerraformPlanNormalizationError,
        match="STS assumed-role ARN",
    ):
        normalize_volatile_caller_identity(payload)


def _resource_change(session: str) -> dict[str, Any]:
    caller = _caller(session=session)
    return {
        "address": CALLER_IDENTITY_ADDRESS,
        "mode": "data",
        "type": "aws_caller_identity",
        "name": "current",
        "change": {
            "actions": ["read"],
            "before": None,
            "after": copy.deepcopy(caller["values"]),
        },
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "planned_values": {
                "root_module": {
                    "child_modules": [
                        {"address": "module.platform", "resources": [_caller(session="one")]}
                    ]
                }
            }
        },
        {
            "prior_state": {
                "values": {
                    "root_module": {
                        "child_modules": [
                            {
                                "address": "module.platform",
                                "resources": [_caller(session="two")],
                            }
                        ]
                    }
                }
            }
        },
        {"resource_changes": [_resource_change("three")]},
        {"resource_drift": [_resource_change("four")]},
        {"deferred_changes": [{"resource_change": _resource_change("five")}]},
    ],
    ids=[
        "planned-values",
        "prior-state",
        "resource-changes",
        "resource-drift",
        "deferred-changes",
    ],
)
def test_each_supported_terraform_resource_location_is_normalized(
    payload: dict[str, Any],
) -> None:
    serialized = json.dumps(normalize_volatile_caller_identity(payload), sort_keys=True)

    assert VOLATILE_STS_SESSION_SENTINEL in serialized


@pytest.mark.parametrize("missing_field", ["account_id", "arn", "id", "user_id"])
def test_missing_caller_value_field_fails_closed(missing_field: str) -> None:
    payload = {"resource_changes": [_resource_change("one")]}
    del payload["resource_changes"][0]["change"]["after"][missing_field]

    with pytest.raises(
        TerraformPlanNormalizationError,
        match="missing required fields",
    ):
        normalize_volatile_caller_identity(payload)


def test_unordered_relevant_attributes_have_the_same_digest() -> None:
    first = _plan(session="same")
    second = copy.deepcopy(first)
    first["relevant_attributes"] = [
        {"resource": "module.platform.data.aws_partition.current", "attribute": ["id"]},
        {
            "resource": CALLER_IDENTITY_ADDRESS,
            "attribute": ["account_id"],
        },
    ]
    second["relevant_attributes"] = list(reversed(first["relevant_attributes"]))

    assert _workflow_digest(first) == _workflow_digest(second)


@pytest.mark.parametrize(
    "changed_entry",
    [
        {"resource": "module.platform.data.aws_partition.other", "attribute": ["id"]},
        {"resource": "module.platform.data.aws_partition.current", "attribute": ["partition"]},
    ],
)
def test_relevant_attribute_members_and_paths_remain_hash_bound(
    changed_entry: dict[str, Any],
) -> None:
    original = _plan(session="same")
    changed = copy.deepcopy(original)
    original["relevant_attributes"] = [
        {"resource": "module.platform.data.aws_partition.current", "attribute": ["id"]}
    ]
    changed["relevant_attributes"] = [changed_entry]

    assert _workflow_digest(original) != _workflow_digest(changed)


def test_relevant_attribute_path_order_and_duplicates_remain_hash_bound() -> None:
    original = _plan(session="same")
    reordered_path = copy.deepcopy(original)
    duplicate = copy.deepcopy(original)
    entry = {
        "resource": "module.platform.aws_iam_role_policy.workflow",
        "attribute": ["policy", 0, "statement"],
    }
    original["relevant_attributes"] = [entry]
    reordered_path["relevant_attributes"] = [{**entry, "attribute": ["statement", 0, "policy"]}]
    duplicate["relevant_attributes"] = [entry, copy.deepcopy(entry)]

    assert _workflow_digest(original) != _workflow_digest(reordered_path)
    assert _workflow_digest(original) != _workflow_digest(duplicate)


def test_managed_resource_order_is_not_broadly_normalized() -> None:
    original = _plan(session="same")
    reordered = copy.deepcopy(original)
    reordered_resources = reordered["planned_values"]["root_module"]["child_modules"][0][
        "resources"
    ]
    reordered_resources.reverse()

    assert _workflow_digest(original) != _workflow_digest(reordered)


@pytest.mark.parametrize(
    "relevant_attributes",
    [
        None,
        {},
        ["not-an-object"],
        [{"resource": 1, "attribute": ["id"]}],
        [{"resource": CALLER_IDENTITY_ADDRESS, "attribute": "account_id"}],
        [{"resource": "", "attribute": ["account_id"]}],
        [{"resource": CALLER_IDENTITY_ADDRESS, "attribute": [True]}],
        [{"resource": CALLER_IDENTITY_ADDRESS, "attribute": [{}]}],
        [{"resource": CALLER_IDENTITY_ADDRESS, "attribute": [], "extra": "field"}],
    ],
)
def test_malformed_relevant_attributes_fail_closed(relevant_attributes: object) -> None:
    payload = _plan(session="same")
    payload["relevant_attributes"] = relevant_attributes

    with pytest.raises(TerraformPlanNormalizationError, match="relevant_attributes"):
        canonicalize_terraform_plan(payload)
