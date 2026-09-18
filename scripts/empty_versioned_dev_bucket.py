"""Empty one exact disposable-dev S3 bucket, including versions and multipart uploads."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROJECT = "product-search-ranking"
REGION = "us-east-1"
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")


class DevBucketCleanupError(RuntimeError):
    """The bucket target or version-aware cleanup failed closed."""


def expected_bucket_name(account_id: str, kind: str) -> str:
    if ACCOUNT_RE.fullmatch(account_id) is None:
        raise DevBucketCleanupError("account_id must be exactly 12 decimal digits")
    if kind not in {"artifacts", "site"}:
        raise DevBucketCleanupError("kind must be exactly artifacts or site")
    return f"{PROJECT}-dev-{account_id}-{REGION}-{kind}"


def _version_entries(client: Any, bucket: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        for collection in ("Versions", "DeleteMarkers"):
            values = page.get(collection, [])
            if not isinstance(values, list):
                raise DevBucketCleanupError("S3 returned an invalid object-version collection")
            for value in values:
                if not isinstance(value, dict):
                    raise DevBucketCleanupError("S3 returned an invalid object-version record")
                key = value.get("Key")
                version_id = value.get("VersionId")
                if not isinstance(key, str) or not isinstance(version_id, str):
                    raise DevBucketCleanupError("S3 object-version identity is incomplete")
                entries.append({"Key": key, "VersionId": version_id})
    return entries


def _multipart_entries(client: Any, bucket: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    paginator = client.get_paginator("list_multipart_uploads")
    for page in paginator.paginate(Bucket=bucket):
        uploads = page.get("Uploads", [])
        if not isinstance(uploads, list):
            raise DevBucketCleanupError("S3 returned an invalid multipart-upload collection")
        for value in uploads:
            if not isinstance(value, dict):
                raise DevBucketCleanupError("S3 returned an invalid multipart-upload record")
            key = value.get("Key")
            upload_id = value.get("UploadId")
            if not isinstance(key, str) or not isinstance(upload_id, str):
                raise DevBucketCleanupError("S3 multipart-upload identity is incomplete")
            entries.append({"Key": key, "UploadId": upload_id})
    return entries


def empty_bucket(client: Any, bucket: str) -> dict[str, int]:
    versions = _version_entries(client, bucket)
    uploads = _multipart_entries(client, bucket)
    deleted = 0
    for offset in range(0, len(versions), 1000):
        batch = versions[offset : offset + 1000]
        response = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": batch, "Quiet": False},
        )
        errors = response.get("Errors", [])
        if errors:
            raise DevBucketCleanupError(
                f"S3 rejected {len(errors)} version deletions; no identifiers were emitted"
            )
        deleted += len(batch)
    for upload in uploads:
        client.abort_multipart_upload(
            Bucket=bucket,
            Key=upload["Key"],
            UploadId=upload["UploadId"],
        )

    remaining_versions = _version_entries(client, bucket)
    remaining_uploads = _multipart_entries(client, bucket)
    if remaining_versions or remaining_uploads:
        raise DevBucketCleanupError(
            "version-aware cleanup left residual entries "
            f"(versions={len(remaining_versions)}, multipart={len(remaining_uploads)})"
        )
    return {
        "aborted_multipart_uploads": len(uploads),
        "deleted_versions_and_markers": deleted,
        "remaining_multipart_uploads": 0,
        "remaining_versions_and_markers": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--kind", choices=("artifacts", "site"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    import boto3

    bucket = expected_bucket_name(args.account_id, args.kind)
    result = empty_bucket(boto3.client("s3", region_name=REGION), bucket)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "Disposable dev bucket emptied "
        f"(versions={result['deleted_versions_and_markers']}, "
        f"multipart={result['aborted_multipart_uploads']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
