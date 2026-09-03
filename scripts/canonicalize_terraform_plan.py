"""Normalize only volatile Terraform plan fields before canonical hashing."""

from __future__ import annotations

import copy
import re
from typing import Any

CALLER_IDENTITY_ADDRESS = "module.platform.data.aws_caller_identity.current"
CALLER_IDENTITY_MODE = "data"
CALLER_IDENTITY_TYPE = "aws_caller_identity"
CALLER_IDENTITY_NAME = "current"
VOLATILE_STS_SESSION_SENTINEL = "<volatile-sts-session>"

_ASSUMED_ROLE_ARN = re.compile(r"^(arn:[a-z0-9-]+:sts::([0-9]{12}):assumed-role/.+)/([^/]+)$")
_ASSUMED_ROLE_USER_ID = re.compile(r"^([A-Z0-9]+):([^:]+)$")
_AWS_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
_CALLER_VALUE_FIELDS = frozenset({"account_id", "arn", "id", "user_id"})


class TerraformPlanNormalizationError(ValueError):
    """The caller-identity record is not the exact expected Terraform shape."""


def _normalize_assumed_role_arn(value: object, *, account_id: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise TerraformPlanNormalizationError("caller identity ARN must be a string")
    match = _ASSUMED_ROLE_ARN.fullmatch(value)
    if match is None:
        raise TerraformPlanNormalizationError("caller identity must be an STS assumed-role ARN")
    if match.group(2) != account_id:
        raise TerraformPlanNormalizationError("caller identity ARN account must match account_id")
    return f"{match.group(1)}/{VOLATILE_STS_SESSION_SENTINEL}", match.group(3)


def _normalize_assumed_role_user_id(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise TerraformPlanNormalizationError("caller identity user ID must be a string")
    match = _ASSUMED_ROLE_USER_ID.fullmatch(value)
    if match is None:
        raise TerraformPlanNormalizationError("caller identity user ID is malformed")
    return f"{match.group(1)}:{VOLATILE_STS_SESSION_SENTINEL}", match.group(2)


def _normalize_caller_values(values: object) -> bool:
    if values is None:
        return False
    if not isinstance(values, dict):
        raise TerraformPlanNormalizationError("caller identity values must be an object")
    missing = _CALLER_VALUE_FIELDS.difference(values)
    if missing:
        raise TerraformPlanNormalizationError(
            f"caller identity values are missing required fields: {', '.join(sorted(missing))}"
        )
    account_id = values["account_id"]
    if not isinstance(account_id, str) or _AWS_ACCOUNT_ID.fullmatch(account_id) is None:
        raise TerraformPlanNormalizationError(
            "caller identity account_id must be a 12-digit string"
        )
    if values["id"] != account_id:
        raise TerraformPlanNormalizationError("caller identity id must match account_id")
    normalized_arn, arn_session = _normalize_assumed_role_arn(values["arn"], account_id=account_id)
    normalized_user_id, user_id_session = _normalize_assumed_role_user_id(values["user_id"])
    if arn_session != user_id_session:
        raise TerraformPlanNormalizationError("caller identity ARN and user ID sessions must match")
    values["arn"] = normalized_arn
    values["user_id"] = normalized_user_id
    return True


def _normalize_resource_envelope(resource: object) -> int:
    if not isinstance(resource, dict):
        raise TerraformPlanNormalizationError("Terraform resource record must be an object")
    if resource.get("address") != CALLER_IDENTITY_ADDRESS:
        return 0
    expected = {
        "mode": CALLER_IDENTITY_MODE,
        "type": CALLER_IDENTITY_TYPE,
        "name": CALLER_IDENTITY_NAME,
    }
    if any(resource.get(key) != value for key, value in expected.items()):
        raise TerraformPlanNormalizationError(
            "caller identity address is attached to an unexpected resource envelope"
        )
    normalized_value_sets = int(_normalize_caller_values(resource.get("values")))
    change = resource.get("change")
    if change is not None:
        if not isinstance(change, dict):
            raise TerraformPlanNormalizationError("caller identity change must be an object")
        normalized_value_sets += int(_normalize_caller_values(change.get("before")))
        normalized_value_sets += int(_normalize_caller_values(change.get("after")))
    if normalized_value_sets == 0:
        raise TerraformPlanNormalizationError(
            "caller identity resource has no concrete values to normalize"
        )
    return normalized_value_sets


def _normalize_module(module: object) -> int:
    if not isinstance(module, dict):
        raise TerraformPlanNormalizationError("Terraform module record must be an object")
    resources = module.get("resources", [])
    if not isinstance(resources, list):
        raise TerraformPlanNormalizationError("Terraform module resources must be a list")
    normalized_value_sets = sum(_normalize_resource_envelope(resource) for resource in resources)
    child_modules = module.get("child_modules", [])
    if not isinstance(child_modules, list):
        raise TerraformPlanNormalizationError("Terraform child modules must be a list")
    for child in child_modules:
        normalized_value_sets += _normalize_module(child)
    return normalized_value_sets


def _normalize_values_tree(container: object) -> int:
    if container is None:
        return 0
    if not isinstance(container, dict):
        raise TerraformPlanNormalizationError("Terraform values container must be an object")
    root_module = container.get("root_module")
    if root_module is not None:
        return _normalize_module(root_module)
    return 0


def _normalize_resource_list(payload: dict[str, Any], key: str) -> int:
    resources = payload.get(key, [])
    if not isinstance(resources, list):
        raise TerraformPlanNormalizationError(f"Terraform {key} must be a list")
    return sum(_normalize_resource_envelope(resource) for resource in resources)


def normalize_volatile_caller_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize only STS session suffixes in known caller-identity resource records."""

    normalized = copy.deepcopy(payload)
    normalized_value_sets = _normalize_values_tree(normalized.get("planned_values"))
    prior_state = normalized.get("prior_state")
    if prior_state is not None:
        if not isinstance(prior_state, dict):
            raise TerraformPlanNormalizationError("Terraform prior state must be an object")
        normalized_value_sets += _normalize_values_tree(prior_state.get("values"))
    normalized_value_sets += _normalize_resource_list(normalized, "resource_changes")
    normalized_value_sets += _normalize_resource_list(normalized, "resource_drift")
    deferred = normalized.get("deferred_changes", [])
    if not isinstance(deferred, list):
        raise TerraformPlanNormalizationError("Terraform deferred changes must be a list")
    for item in deferred:
        if not isinstance(item, dict):
            raise TerraformPlanNormalizationError("Terraform deferred change must be an object")
        resource_change = item.get("resource_change")
        if resource_change is not None:
            normalized_value_sets += _normalize_resource_envelope(resource_change)
    if normalized_value_sets == 0:
        raise TerraformPlanNormalizationError(
            "Terraform plan contains no concrete caller identity values"
        )
    return normalized
