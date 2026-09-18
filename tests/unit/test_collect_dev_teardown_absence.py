from __future__ import annotations

from typing import Any

import pytest

from scripts.collect_dev_teardown_absence import (
    DevAbsenceCollectionError,
    collect_absence,
)


class _AwsError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}


class _Paginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages

    def paginate(self, **_: object) -> list[dict[str, Any]]:
        return self.pages


class _InventoryClient:
    def __init__(self, service: str) -> None:
        self.service = service

    def get_paginator(self, operation: str) -> _Paginator:
        pages: dict[str, list[dict[str, Any]]] = {
            "describe_log_groups": [{"logGroups": []}],
            "get_apis": [{"Items": []}],
            "list_distributions": [{"DistributionList": {"Items": []}}],
            "list_functions": [{"FunctionList": {"Items": []}}],
            "list_origin_access_controls": [{"OriginAccessControlList": {"Items": []}}],
            "list_processing_jobs": [{"ProcessingJobSummaries": []}],
            "list_response_headers_policies": [{"ResponseHeadersPolicyList": {"Items": []}}],
            "list_rules": [{"Rules": []}],
            "list_topics": [{"Topics": []}],
            "list_training_jobs": [{"TrainingJobSummaries": []}],
        }
        return _Paginator(pages[operation])

    def head_bucket(self, **_: object) -> None:
        raise _AwsError("404")

    def get_bucket_location(self, **_: object) -> dict[str, object]:
        return {"LocationConstraint": None}

    def describe_repositories(self, **_: object) -> None:
        raise _AwsError("RepositoryNotFoundException")

    def get_role(self, **_: object) -> None:
        raise _AwsError("NoSuchEntity")

    def get_function(self, **_: object) -> None:
        raise _AwsError("ResourceNotFoundException")

    def describe_budget(self, **_: object) -> None:
        raise _AwsError("NotFoundException")


def _clients() -> dict[str, _InventoryClient]:
    return {
        service: _InventoryClient(service)
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


def test_absence_collector_emits_only_zero_counts_and_state_retention() -> None:
    result = collect_absence(_clients(), account_id="123456789012", terraform_state_resources=0)

    assert result["state_backend_retained"] is True
    assert result["residual_counts"]
    assert set(result["residual_counts"].values()) == {0}


def test_absence_collector_fails_closed_on_an_inconclusive_probe() -> None:
    clients = _clients()

    def denied(**_: object) -> None:
        raise _AwsError("AccessDenied")

    clients["s3"].head_bucket = denied  # type: ignore[method-assign]
    with pytest.raises(DevAbsenceCollectionError, match="denied or inconclusive"):
        collect_absence(clients, account_id="123456789012", terraform_state_resources=0)
