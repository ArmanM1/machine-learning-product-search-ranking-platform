from __future__ import annotations

from typing import Any

import pytest

from scripts.empty_dev_repositories import (
    DevRepositoryCleanupError,
    empty_repositories,
    expected_repository_names,
)


class _Paginator:
    def __init__(self, client: _Ecr) -> None:
        self.client = client

    def paginate(self, **_: object) -> list[dict[str, Any]]:
        self.client.list_calls += 1
        if self.client.list_calls % 2 == 1:
            return [
                {
                    "imageIds": [
                        {"imageDigest": "sha256:" + "a" * 64, "imageTag": "fixture"},
                        {"imageDigest": "sha256:" + "b" * 64},
                    ]
                }
            ]
        return [{"imageIds": []}]


class _Ecr:
    def __init__(self) -> None:
        self.list_calls = 0
        self.deleted: list[dict[str, str]] = []

    def get_paginator(self, operation: str) -> _Paginator:
        assert operation == "list_images"
        return _Paginator(self)

    def batch_delete_image(self, **kwargs: Any) -> dict[str, object]:
        self.deleted.extend(kwargs["imageIds"])
        return {"failures": []}


def test_exact_dev_repositories_are_emptied_without_emitting_identities() -> None:
    client = _Ecr()
    result = empty_repositories(client, ("one", "two", "three"))

    assert result == {"deleted_image_identities": 6, "remaining_image_identities": 0}
    assert len(client.deleted) == 6


def test_repository_names_are_exact_and_account_validated() -> None:
    assert expected_repository_names("123456789012") == (
        "product-search-ranking-dev-eval",
        "product-search-ranking-dev-serve",
        "product-search-ranking-dev-train",
    )
    with pytest.raises(DevRepositoryCleanupError):
        expected_repository_names("invalid")
