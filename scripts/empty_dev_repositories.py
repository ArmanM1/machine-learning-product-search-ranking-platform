"""Delete every image from the three exact disposable-dev ECR repositories."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROJECT = "product-search-ranking"
REGION = "us-east-1"
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")


class DevRepositoryCleanupError(RuntimeError):
    """The repository target or image cleanup failed closed."""


def expected_repository_names(account_id: str) -> tuple[str, str, str]:
    if ACCOUNT_RE.fullmatch(account_id) is None:
        raise DevRepositoryCleanupError("account_id must be exactly 12 decimal digits")
    prefix = f"{PROJECT}-dev"
    return tuple(f"{prefix}-{kind}" for kind in ("eval", "serve", "train"))


def _image_ids(client: Any, repository: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    paginator = client.get_paginator("list_images")
    for page in paginator.paginate(repositoryName=repository, filter={"tagStatus": "ANY"}):
        values = page.get("imageIds", [])
        if not isinstance(values, list):
            raise DevRepositoryCleanupError("ECR returned an invalid image inventory")
        for value in values:
            if not isinstance(value, dict):
                raise DevRepositoryCleanupError("ECR returned an invalid image identity")
            image_digest = value.get("imageDigest")
            image_tag = value.get("imageTag")
            if not isinstance(image_digest, str):
                raise DevRepositoryCleanupError("ECR image identity lacks its digest")
            identity = {"imageDigest": image_digest}
            if isinstance(image_tag, str):
                identity["imageTag"] = image_tag
            images.append(identity)
    return images


def empty_repositories(client: Any, repositories: tuple[str, ...]) -> dict[str, int]:
    deleted = 0
    for repository in repositories:
        images = _image_ids(client, repository)
        for offset in range(0, len(images), 100):
            batch = images[offset : offset + 100]
            response = client.batch_delete_image(repositoryName=repository, imageIds=batch)
            failures = response.get("failures", [])
            if failures:
                raise DevRepositoryCleanupError(
                    f"ECR rejected {len(failures)} image deletions; no identifiers were emitted"
                )
            deleted += len(batch)
        if _image_ids(client, repository):
            raise DevRepositoryCleanupError("ECR cleanup left residual images")
    return {"deleted_image_identities": deleted, "remaining_image_identities": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    import boto3

    repositories = expected_repository_names(args.account_id)
    result = empty_repositories(boto3.client("ecr", region_name=REGION), repositories)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Disposable dev repositories emptied (images={result['deleted_image_identities']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
