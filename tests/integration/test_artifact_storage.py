from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from search_rank.artifacts.storage import LocalArtifactStore, S3ArtifactStore

pytestmark = pytest.mark.integration


class FakeObjectClient:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.version_id = "fixture-version-1"

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, object] | None = None,
    ) -> None:
        destination = self.root / bucket / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(filename, destination)
        arguments = ExtraArgs or {}
        metadata = arguments.get("Metadata", {})
        assert isinstance(metadata, dict)
        self.metadata[(bucket, key)] = {str(name): str(value) for name, value in metadata.items()}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        shutil.copy2(self.root / bucket / key, filename)

    def head_object(self, **kwargs: str) -> dict[str, object]:
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        artifact = self.root / bucket / key
        return {
            "Metadata": self.metadata[(bucket, key)],
            "ContentLength": artifact.stat().st_size,
            "VersionId": self.version_id,
        }


def test_local_and_mock_s3_round_trip_with_checksum_verification(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"evidence":"tiny"}\n', encoding="utf-8")

    local = LocalArtifactStore(tmp_path / "local-store")
    checksum = local.upload(source, "runs/tiny/evidence.json")
    local_copy = local.download("runs/tiny/evidence.json", tmp_path / "local.json", checksum)
    assert local_copy.read_bytes() == source.read_bytes()

    client = FakeObjectClient(tmp_path / "object-store")
    remote = S3ArtifactStore("test-bucket", client)
    remote_checksum = remote.upload(source, "runs/tiny/evidence.json")
    assert remote.verified_version("runs/tiny/evidence.json") == "fixture-version-1"
    remote_copy = remote.download(
        "runs/tiny/evidence.json", tmp_path / "remote.json", remote_checksum
    )
    assert remote_copy.read_bytes() == source.read_bytes()

    (tmp_path / "object-store/test-bucket/runs/tiny/evidence.json").write_text(
        "corrupt", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        remote.download("runs/tiny/evidence.json", tmp_path / "corrupt.json", remote_checksum)


def test_s3_upload_fails_when_remote_checksum_does_not_match(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source bytes", encoding="utf-8")
    client = FakeObjectClient(tmp_path / "object-store")
    original_head = client.head_object

    def mismatched_head(**kwargs: str) -> dict[str, object]:
        response = original_head(**kwargs)
        response["Metadata"] = {"sha256": "0" * 64}
        return response

    client.head_object = mismatched_head  # type: ignore[method-assign]
    store = S3ArtifactStore("test-bucket", client)
    with pytest.raises(ValueError, match="remote checksum mismatch"):
        store.upload(source, "runs/tiny/source.txt")


def test_s3_upload_fails_without_version_id(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source bytes", encoding="utf-8")
    client = FakeObjectClient(tmp_path / "object-store")
    client.version_id = "null"
    store = S3ArtifactStore("test-bucket", client)
    with pytest.raises(ValueError, match="versioning enabled"):
        store.upload(source, "runs/tiny/source.txt")


def test_local_store_rejects_path_escape(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    store = LocalArtifactStore(tmp_path / "store")
    with pytest.raises(ValueError, match="escapes"):
        store.upload(source, "../outside.txt")
