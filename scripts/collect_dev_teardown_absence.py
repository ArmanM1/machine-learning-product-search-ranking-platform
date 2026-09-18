"""Collect a sanitized, count-only absence proof for the disposable dev environment."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.dev_teardown_contract import (
    ACCOUNT_RE,
    ENVIRONMENT,
    PROJECT,
    REGION,
    expected_resource_names,
)


class DevAbsenceCollectionError(RuntimeError):
    """An AWS inventory query was inconclusive instead of proving absence."""


def _error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None
    body = response.get("Error")
    if not isinstance(body, dict):
        return None
    code = body.get("Code")
    return code if isinstance(code, str) else None


def _count_existing(
    values: list[str],
    probe: Callable[[str], object],
    *,
    missing_codes: set[str],
) -> int:
    count = 0
    for value in values:
        try:
            probe(value)
        except Exception as error:
            if _error_code(error) in missing_codes:
                continue
            raise DevAbsenceCollectionError(
                "AWS absence probe was denied or inconclusive"
            ) from error
        count += 1
    return count


def _pages(client: Any, operation: str, **kwargs: object) -> list[dict[str, Any]]:
    paginator = client.get_paginator(operation)
    pages = list(paginator.paginate(**kwargs))
    if any(not isinstance(page, dict) for page in pages):
        raise DevAbsenceCollectionError(f"{operation} returned an invalid page")
    return pages


def collect_absence(
    clients: dict[str, Any],
    *,
    account_id: str,
    terraform_state_resources: int,
) -> dict[str, Any]:
    if ACCOUNT_RE.fullmatch(account_id) is None:
        raise DevAbsenceCollectionError("account_id must be exactly 12 decimal digits")
    if isinstance(terraform_state_resources, bool) or terraform_state_resources < 0:
        raise DevAbsenceCollectionError("terraform_state_resources must be a nonnegative integer")

    buckets, repositories, roles, expected_log_groups = expected_resource_names(account_id)
    prefix = f"{PROJECT}-{ENVIRONMENT}"

    s3 = clients["s3"]
    ecr = clients["ecr"]
    iam = clients["iam"]
    lambda_client = clients["lambda"]
    api = clients["apigatewayv2"]
    cloudfront = clients["cloudfront"]
    logs = clients["logs"]
    events = clients["events"]
    sns = clients["sns"]
    budgets_client = clients["budgets"]
    sagemaker = clients["sagemaker"]

    bucket_count = _count_existing(
        sorted(buckets),
        lambda name: s3.head_bucket(Bucket=name),
        missing_codes={"404", "NoSuchBucket", "NotFound"},
    )
    repository_count = _count_existing(
        sorted(repositories),
        lambda name: ecr.describe_repositories(repositoryNames=[name]),
        missing_codes={"RepositoryNotFoundException"},
    )
    role_count = _count_existing(
        sorted(roles),
        lambda name: iam.get_role(RoleName=name),
        missing_codes={"NoSuchEntity", "NoSuchEntityException"},
    )
    lambda_count = _count_existing(
        [f"{prefix}-api", f"{prefix}-api-budget-kill-switch"],
        lambda name: lambda_client.get_function(FunctionName=name),
        missing_codes={"ResourceNotFoundException"},
    )

    api_count = sum(
        1
        for page in _pages(api, "get_apis")
        for item in page.get("Items", [])
        if isinstance(item, dict) and str(item.get("Name", "")).startswith(prefix)
    )
    distribution_count = sum(
        1
        for page in _pages(cloudfront, "list_distributions")
        for item in page.get("DistributionList", {}).get("Items", [])
        if isinstance(item, dict) and item.get("Comment") == prefix
    )
    function_count = sum(
        1
        for page in _pages(cloudfront, "list_functions")
        for item in page.get("FunctionList", {}).get("Items", [])
        if isinstance(item, dict) and item.get("Name") == f"{prefix}-spa-rewrite"
    )
    origin_access_control_count = sum(
        1
        for page in _pages(cloudfront, "list_origin_access_controls")
        for item in page.get("OriginAccessControlList", {}).get("Items", [])
        if isinstance(item, dict) and item.get("Name") == f"{prefix}-site"
    )
    response_headers_policy_count = sum(
        1
        for page in _pages(cloudfront, "list_response_headers_policies", Type="custom")
        for item in page.get("ResponseHeadersPolicyList", {}).get("Items", [])
        if isinstance(item, dict)
        and isinstance(item.get("ResponseHeadersPolicy"), dict)
        and item["ResponseHeadersPolicy"].get("ResponseHeadersPolicyConfig", {}).get("Name")
        == f"{prefix}-security"
    )
    log_group_count = sum(
        1
        for page in _pages(logs, "describe_log_groups", logGroupNamePrefix="/aws/")
        for item in page.get("logGroups", [])
        if isinstance(item, dict) and item.get("logGroupName") in expected_log_groups
    )
    event_rule_count = sum(
        1
        for page in _pages(events, "list_rules", NamePrefix=prefix)
        for item in page.get("Rules", [])
        if isinstance(item, dict) and str(item.get("Name", "")).startswith(prefix)
    )
    topic_count = sum(
        1
        for page in _pages(sns, "list_topics")
        for item in page.get("Topics", [])
        if isinstance(item, dict)
        and isinstance(item.get("TopicArn"), str)
        and item["TopicArn"].rsplit(":", 1)[-1].startswith(prefix)
    )
    budget_count = _count_existing(
        [f"{prefix}-actual", f"{prefix}-forecasted"],
        lambda name: budgets_client.describe_budget(AccountId=account_id, BudgetName=name),
        missing_codes={"NotFoundException"},
    )

    active_training = 0
    active_processing = 0
    for status in ("InProgress", "Stopping"):
        active_training += sum(
            len(page.get("TrainingJobSummaries", []))
            for page in _pages(
                sagemaker,
                "list_training_jobs",
                NameContains=f"{prefix}-",
                StatusEquals=status,
            )
        )
        active_processing += sum(
            len(page.get("ProcessingJobSummaries", []))
            for page in _pages(
                sagemaker,
                "list_processing_jobs",
                NameContains=f"{prefix}-",
                StatusEquals=status,
            )
        )
    endpoint_count = sum(
        len(page.get("Endpoints", []))
        for page in _pages(sagemaker, "list_endpoints", NameContains=f"{prefix}-")
    )

    state_bucket = f"{PROJECT}-terraform-state-{account_id}-{REGION}"
    try:
        location = s3.get_bucket_location(Bucket=state_bucket).get("LocationConstraint")
    except Exception as error:
        raise DevAbsenceCollectionError(
            "protected Terraform state bucket was not retained"
        ) from error
    if location not in (None, "us-east-1"):
        raise DevAbsenceCollectionError("protected Terraform state bucket is outside us-east-1")

    return {
        "residual_counts": {
            "active_processing_jobs": active_processing,
            "active_training_jobs": active_training,
            "api_gateways": api_count,
            "budgets": budget_count,
            "cloudfront_distributions": distribution_count,
            "cloudfront_functions": function_count,
            "cloudfront_origin_access_controls": origin_access_control_count,
            "cloudfront_response_headers_policies": response_headers_policy_count,
            "ecr_repositories": repository_count,
            "event_rules": event_rule_count,
            "iam_roles": role_count,
            "lambda_functions": lambda_count,
            "log_groups": log_group_count,
            "s3_buckets": bucket_count,
            "sagemaker_endpoints": endpoint_count,
            "sns_topics": topic_count,
            "terraform_state_resources": terraform_state_resources,
        },
        "state_backend_retained": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--terraform-state-resources", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    import boto3

    session = boto3.session.Session(region_name=REGION)
    clients = {
        service: session.client(service, region_name=REGION)
        for service in (
            "apigatewayv2",
            "budgets",
            "cloudfront",
            "ecr",
            "events",
            "iam",
            "lambda",
            "logs",
            "s3",
            "sagemaker",
            "sns",
        )
    }
    caller = session.client("sts", region_name=REGION).get_caller_identity()
    if caller.get("Account") != args.account_id:
        raise DevAbsenceCollectionError("live AWS account differs from the attested account")
    result = collect_absence(
        clients,
        account_id=args.account_id,
        terraform_state_resources=args.terraform_state_resources,
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    residual_total = sum(result["residual_counts"].values())
    print(f"Disposable dev residual inventory collected (count={residual_total}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
