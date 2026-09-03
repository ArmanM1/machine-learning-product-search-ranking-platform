from __future__ import annotations

from typing import Any

import pytest

from search_rank.serving import budget_kill_switch


class FakeLambdaClient:
    def __init__(self, concurrency: int | None) -> None:
        self.concurrency = concurrency
        self.put_calls: list[dict[str, Any]] = []

    def get_function_concurrency(self, **kwargs: Any) -> dict[str, int]:
        assert kwargs == {"FunctionName": "product-search-ranking-prod-api"}
        if self.concurrency is None:
            return {}
        return {"ReservedConcurrentExecutions": self.concurrency}

    def put_function_concurrency(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        self.concurrency = kwargs["ReservedConcurrentExecutions"]


class FakeCloudFrontClient:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.update_calls: list[dict[str, Any]] = []

    def get_distribution_config(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"Id": "E123EXAMPLE"}
        return {
            "ETag": "etag-1",
            "DistributionConfig": {
                "CallerReference": "immutable",
                "Comment": "public ranker",
                "Enabled": self.enabled,
            },
        }

    def update_distribution(self, **kwargs: Any) -> None:
        self.update_calls.append(kwargs)
        self.enabled = kwargs["DistributionConfig"]["Enabled"]


def _event(topic_arn: str = "arn:aws:sns:us-east-1:123456789012:budget-kill") -> dict[str, Any]:
    return {
        "Records": [
            {
                "EventSource": "aws:sns",
                "Sns": {"TopicArn": topic_arn, "Message": "untrusted payload is unused"},
            }
        ]
    }


def _expiry_event(
    rule_arn: str = "arn:aws:events:us-east-1:123456789012:rule/public-expiry",
) -> dict[str, Any]:
    return {
        "version": "0",
        "source": "aws.events",
        "detail-type": "Scheduled Event",
        "resources": [rule_arn],
        "detail": {},
    }


def _configure(monkeypatch: pytest.MonkeyPatch, *, budget_topic: str = "") -> None:
    monkeypatch.setenv("RANKER_FUNCTION_NAME", "product-search-ranking-prod-api")
    monkeypatch.setenv("CLOUDFRONT_DISTRIBUTION_ID", "E123EXAMPLE")
    monkeypatch.setenv(
        "EXPIRY_EVENT_RULE_ARN",
        "arn:aws:events:us-east-1:123456789012:rule/public-expiry",
    )
    monkeypatch.setenv("BUDGET_SNS_TOPIC_ARN", budget_topic)


def test_enforce_kill_switch_stops_ranker_before_disabling_distribution() -> None:
    order: list[str] = []
    lambda_client = FakeLambdaClient(2)
    cloudfront_client = FakeCloudFrontClient(enabled=True)
    original_put = lambda_client.put_function_concurrency
    original_update = cloudfront_client.update_distribution

    def put(**kwargs: Any) -> None:
        order.append("lambda")
        original_put(**kwargs)

    def update(**kwargs: Any) -> None:
        order.append("cloudfront")
        original_update(**kwargs)

    lambda_client.put_function_concurrency = put  # type: ignore[method-assign]
    cloudfront_client.update_distribution = update  # type: ignore[method-assign]

    result = budget_kill_switch.enforce_kill_switch(
        lambda_client=lambda_client,
        cloudfront_client=cloudfront_client,
        ranker_function_name="product-search-ranking-prod-api",
        cloudfront_distribution_id="E123EXAMPLE",
    )

    assert order == ["lambda", "cloudfront"]
    assert lambda_client.put_calls == [
        {
            "FunctionName": "product-search-ranking-prod-api",
            "ReservedConcurrentExecutions": 0,
        }
    ]
    assert cloudfront_client.update_calls == [
        {
            "Id": "E123EXAMPLE",
            "IfMatch": "etag-1",
            "DistributionConfig": {
                "CallerReference": "immutable",
                "Comment": "public ranker",
                "Enabled": False,
            },
        }
    ]
    assert result["ranker"]["changed"] is True
    assert result["cloudfront"]["changed"] is True


def test_enforce_kill_switch_is_idempotent_when_controls_are_already_disabled() -> None:
    lambda_client = FakeLambdaClient(0)
    cloudfront_client = FakeCloudFrontClient(enabled=False)

    result = budget_kill_switch.enforce_kill_switch(
        lambda_client=lambda_client,
        cloudfront_client=cloudfront_client,
        ranker_function_name="product-search-ranking-prod-api",
        cloudfront_distribution_id="E123EXAMPLE",
    )

    assert lambda_client.put_calls == []
    assert cloudfront_client.update_calls == []
    assert result["ranker"] == {
        "function_name": "product-search-ranking-prod-api",
        "previous_reserved_concurrency": 0,
        "reserved_concurrency": 0,
        "changed": False,
    }
    assert result["cloudfront"]["changed"] is False


def test_handler_rejects_any_topic_other_than_the_bound_budget_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        budget_topic="arn:aws:sns:us-east-1:123456789012:expected",
    )

    with pytest.raises(ValueError, match="unexpected SNS topic"):
        budget_kill_switch.handler(_event(), None)


def test_handler_returns_structured_trip_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    topic_arn = "arn:aws:sns:us-east-1:123456789012:expected"
    _configure(monkeypatch, budget_topic=topic_arn)
    lambda_client = FakeLambdaClient(None)
    cloudfront_client = FakeCloudFrontClient(enabled=True)
    clients = {"lambda": lambda_client, "cloudfront": cloudfront_client}
    monkeypatch.setattr(budget_kill_switch.boto3, "client", clients.__getitem__)

    result = budget_kill_switch.handler(_event(topic_arn), None)

    assert result["schema_version"] == 1
    assert result["action"] == "public_cost_kill_switch"
    assert result["trigger"] == "aws_budget_sns"
    assert result["sns_record_count"] == 1
    assert result["ranker"]["reserved_concurrency"] == 0
    assert result["cloudfront"]["enabled"] is False


def test_handler_accepts_exact_budget_independent_expiry_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    lambda_client = FakeLambdaClient(2)
    cloudfront_client = FakeCloudFrontClient(enabled=True)
    clients = {"lambda": lambda_client, "cloudfront": cloudfront_client}
    monkeypatch.setattr(budget_kill_switch.boto3, "client", clients.__getitem__)

    result = budget_kill_switch.handler(_expiry_event(), None)

    assert result["trigger"] == "public_serving_expiry"
    assert result["sns_record_count"] == 0
    assert result["ranker"]["reserved_concurrency"] == 0
    assert result["cloudfront"]["enabled"] is False


def test_handler_rejects_a_different_expiry_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    with pytest.raises(ValueError, match="unexpected rule"):
        budget_kill_switch.handler(
            _expiry_event("arn:aws:events:us-east-1:123456789012:rule/other"), None
        )


def test_budget_trigger_is_rejected_when_owner_waived_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)

    with pytest.raises(ValueError, match="not configured"):
        budget_kill_switch.handler(_event(), None)
