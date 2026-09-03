"""Budget-independent public-serving expiry and optional AWS Budget kill switch.

The handler is intentionally independent of the ranking application startup path.  It is
invoked by the exact EventBridge expiry rule or the optional dedicated budget SNS topic. It
performs two idempotent control-plane updates: throttle the public ranker to zero concurrency,
then disable its CloudFront distribution.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import boto3  # type: ignore[import-untyped]

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class KillSwitchSettings:
    """Exact AWS resources the dedicated execution role is allowed to stop."""

    ranker_function_name: str
    cloudfront_distribution_id: str
    expiry_rule_arn: str
    budget_topic_arn: str | None

    @classmethod
    def from_environment(cls) -> KillSwitchSettings:
        values = {
            "ranker_function_name": os.environ.get("RANKER_FUNCTION_NAME", "").strip(),
            "cloudfront_distribution_id": os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "").strip(),
            "budget_topic_arn": os.environ.get("BUDGET_SNS_TOPIC_ARN", "").strip(),
            "expiry_rule_arn": os.environ.get("EXPIRY_EVENT_RULE_ARN", "").strip(),
        }
        required = ("ranker_function_name", "cloudfront_distribution_id", "expiry_rule_arn")
        missing = sorted(name for name in required if not values[name])
        if missing:
            raise RuntimeError(
                "budget kill-switch configuration is incomplete: " + ", ".join(missing)
            )
        return cls(
            ranker_function_name=values["ranker_function_name"],
            cloudfront_distribution_id=values["cloudfront_distribution_id"],
            expiry_rule_arn=values["expiry_rule_arn"],
            budget_topic_arn=values["budget_topic_arn"] or None,
        )


def _validate_sns_event(event: Mapping[str, Any], *, expected_topic_arn: str) -> int:
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        raise ValueError("budget kill switch requires at least one SNS record")

    for record in records:
        if not isinstance(record, Mapping) or record.get("EventSource") != "aws:sns":
            raise ValueError("budget kill switch accepts only SNS records")
        sns = record.get("Sns")
        if not isinstance(sns, Mapping) or sns.get("TopicArn") != expected_topic_arn:
            raise ValueError("budget kill switch received a record from an unexpected SNS topic")
    return len(records)


def _validate_expiry_event(event: Mapping[str, Any], *, expected_rule_arn: str) -> None:
    if event.get("source") != "aws.events" or event.get("detail-type") != "Scheduled Event":
        raise ValueError("public-serving expiry accepts only a scheduled EventBridge event")
    resources = event.get("resources")
    if not isinstance(resources, list) or resources != [expected_rule_arn]:
        raise ValueError("public-serving expiry received an event from an unexpected rule")


def _validate_trigger(event: Mapping[str, Any], *, settings: KillSwitchSettings) -> tuple[str, int]:
    if "Records" in event:
        if settings.budget_topic_arn is None:
            raise ValueError("budget-triggered shutdown is not configured")
        return (
            "aws_budget_sns",
            _validate_sns_event(event, expected_topic_arn=settings.budget_topic_arn),
        )
    _validate_expiry_event(event, expected_rule_arn=settings.expiry_rule_arn)
    return "public_serving_expiry", 0


def enforce_kill_switch(
    *,
    lambda_client: Any,
    cloudfront_client: Any,
    ranker_function_name: str,
    cloudfront_distribution_id: str,
) -> dict[str, Any]:
    """Stop the public ranker and distribution without relying on their prior state."""

    concurrency = lambda_client.get_function_concurrency(FunctionName=ranker_function_name)
    previous_concurrency = concurrency.get("ReservedConcurrentExecutions")
    concurrency_changed = previous_concurrency != 0
    if concurrency_changed:
        lambda_client.put_function_concurrency(
            FunctionName=ranker_function_name,
            ReservedConcurrentExecutions=0,
        )

    distribution = cloudfront_client.get_distribution_config(Id=cloudfront_distribution_id)
    etag = distribution.get("ETag")
    distribution_config = distribution.get("DistributionConfig")
    if not isinstance(etag, str) or not etag:
        raise RuntimeError("CloudFront did not return a distribution configuration ETag")
    if not isinstance(distribution_config, Mapping):
        raise RuntimeError("CloudFront did not return a distribution configuration")

    was_enabled = distribution_config.get("Enabled") is True
    if was_enabled:
        disabled_config = deepcopy(dict(distribution_config))
        disabled_config["Enabled"] = False
        cloudfront_client.update_distribution(
            Id=cloudfront_distribution_id,
            IfMatch=etag,
            DistributionConfig=disabled_config,
        )

    return {
        "schema_version": 1,
        "action": "public_cost_kill_switch",
        "ranker": {
            "function_name": ranker_function_name,
            "previous_reserved_concurrency": previous_concurrency,
            "reserved_concurrency": 0,
            "changed": concurrency_changed,
        },
        "cloudfront": {
            "distribution_id": cloudfront_distribution_id,
            "previously_enabled": was_enabled,
            "enabled": False,
            "changed": was_enabled,
        },
    }


def handler(event: Mapping[str, Any], _context: Any) -> dict[str, Any]:
    """Validate the exact source, trip both controls, and emit structured evidence."""

    settings = KillSwitchSettings.from_environment()
    trigger, record_count = _validate_trigger(event, settings=settings)
    result = enforce_kill_switch(
        lambda_client=boto3.client("lambda"),
        cloudfront_client=boto3.client("cloudfront"),
        ranker_function_name=settings.ranker_function_name,
        cloudfront_distribution_id=settings.cloudfront_distribution_id,
    )
    result["trigger"] = trigger
    result["sns_record_count"] = record_count
    LOGGER.warning(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return result


__all__ = ["KillSwitchSettings", "enforce_kill_switch", "handler"]
