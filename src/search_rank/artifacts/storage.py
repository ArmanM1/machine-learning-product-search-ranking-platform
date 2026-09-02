"""Checksum-verifying local and S3 artifact adapters."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from search_rank.artifacts.checksums import sha256_file, verify_file


class ObjectClient(Protocol):
    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, Any] | None = None,
    ) -> object: ...

    def download_file(self, bucket: str, key: str, filename: str) -> object: ...

    def head_object(self, **kwargs: str) -> Mapping[str, object]: ...


class LocalArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def upload(self, source: str | Path, key: str) -> str:
        source_path = Path(source)
        destination = (self.root / key).resolve()
        if self.root not in destination.parents:
            raise ValueError("artifact key escapes the configured store")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        return f"sha256:{sha256_file(destination)}"

    def download(self, key: str, destination: str | Path, expected_checksum: str) -> Path:
        source = (self.root / key).resolve()
        if self.root not in source.parents or not source.is_file():
            raise FileNotFoundError(f"artifact does not exist: {key}")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        verify_file(target, expected_checksum)
        return target


class S3ArtifactStore:
    """Small injectable adapter; IAM and encryption live in Terraform."""

    def __init__(self, bucket: str, client: ObjectClient) -> None:
        if not bucket.strip():
            raise ValueError("bucket must be non-empty")
        self.bucket = bucket
        self.client = client
        self._verified_versions: dict[str, str] = {}

    def upload(self, source: str | Path, key: str) -> str:
        source_path = Path(source)
        digest = sha256_file(source_path)
        checksum = f"sha256:{digest}"
        self.client.upload_file(
            str(source_path),
            self.bucket,
            key,
            ExtraArgs={"Metadata": {"sha256": digest}},
        )
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        metadata_value = response.get("Metadata")
        metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
        remote_digest = metadata.get("sha256")
        if remote_digest != digest:
            raise ValueError(
                f"remote checksum mismatch for s3://{self.bucket}/{key}: "
                f"expected {digest}, got {remote_digest!r}"
            )
        content_length = response.get("ContentLength")
        if content_length != source_path.stat().st_size:
            raise ValueError(
                f"remote size mismatch for s3://{self.bucket}/{key}: "
                f"expected {source_path.stat().st_size}, got {content_length!r}"
            )
        version_id = response.get("VersionId")
        if not isinstance(version_id, str) or not version_id or version_id == "null":
            raise ValueError("artifact upload requires an S3 bucket with versioning enabled")
        self._verified_versions[key] = version_id
        return checksum

    def verified_version(self, key: str) -> str:
        """Return the S3 version observed during checksum verification."""

        try:
            return self._verified_versions[key]
        except KeyError as exc:
            raise KeyError(f"no verified upload exists for artifact key: {key}") from exc

    def download(self, key: str, destination: str | Path, expected_checksum: str) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(target))
        verify_file(target, expected_checksum)
        return target


__all__ = ["LocalArtifactStore", "ObjectClient", "S3ArtifactStore"]
