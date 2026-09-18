from __future__ import annotations

from typing import Any

import pytest

from scripts.empty_versioned_dev_bucket import (
    DevBucketCleanupError,
    empty_bucket,
    expected_bucket_name,
)


class _Paginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages

    def paginate(self, **_: object) -> list[dict[str, Any]]:
        return self.pages


class _S3:
    def __init__(self) -> None:
        self.version_calls = 0
        self.multipart_calls = 0
        self.deleted: list[dict[str, str]] = []
        self.aborted: list[dict[str, str]] = []

    def get_paginator(self, operation: str) -> _Paginator:
        if operation == "list_object_versions":
            self.version_calls += 1
            if self.version_calls == 1:
                return _Paginator(
                    [
                        {
                            "Versions": [{"Key": "one", "VersionId": "v1"}],
                            "DeleteMarkers": [{"Key": "two", "VersionId": "v2"}],
                        }
                    ]
                )
            return _Paginator([{}])
        if operation == "list_multipart_uploads":
            self.multipart_calls += 1
            if self.multipart_calls == 1:
                return _Paginator([{"Uploads": [{"Key": "large", "UploadId": "upload"}]}])
            return _Paginator([{}])
        raise AssertionError(operation)

    def delete_objects(self, **kwargs: Any) -> dict[str, object]:
        self.deleted.extend(kwargs["Delete"]["Objects"])
        return {"Deleted": kwargs["Delete"]["Objects"]}

    def abort_multipart_upload(self, **kwargs: str) -> None:
        self.aborted.append(kwargs)


def test_version_aware_cleanup_deletes_versions_markers_and_multipart_uploads() -> None:
    client = _S3()
    result = empty_bucket(client, "validated-before-call")

    assert result == {
        "aborted_multipart_uploads": 1,
        "deleted_versions_and_markers": 2,
        "remaining_multipart_uploads": 0,
        "remaining_versions_and_markers": 0,
    }
    assert client.deleted == [
        {"Key": "one", "VersionId": "v1"},
        {"Key": "two", "VersionId": "v2"},
    ]
    assert client.aborted == [
        {"Bucket": "validated-before-call", "Key": "large", "UploadId": "upload"}
    ]


def test_target_name_is_exactly_dev_and_account_scoped() -> None:
    assert (
        expected_bucket_name("123456789012", "artifacts")
        == "product-search-ranking-dev-123456789012-us-east-1-artifacts"
    )
    with pytest.raises(DevBucketCleanupError):
        expected_bucket_name("123", "artifacts")
    with pytest.raises(DevBucketCleanupError):
        expected_bucket_name("123456789012", "production")
