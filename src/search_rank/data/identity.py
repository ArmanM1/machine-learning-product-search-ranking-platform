"""Canonical semantic identity for one prepared dataset release."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from search_rank.config import sha256_value
from search_rank.schemas.dataset import DatasetManifest

DATASET_IDENTITY_VERSION = "dataset-manifest-identity-v2"
_TRANSPORT_FIELDS = {"created_at", "processed_artifact_uri", "processed_checksum"}


def dataset_identity_payload(
    manifest: DatasetManifest | Mapping[str, Any],
    artifact_checksums: Mapping[str, str],
) -> dict[str, Any]:
    """Return the exact payload covered by ``processed_checksum``.

    Transport location, transport timestamp, and the checksum itself are excluded to avoid a
    circular identity. Every other manifest field and every prepared artifact byte checksum is
    covered, so altering source, license, split, count, or diagnostic claims fails closed.
    """

    if isinstance(manifest, DatasetManifest):
        semantic_manifest = manifest.model_dump(mode="json", exclude=_TRANSPORT_FIELDS)
    else:
        semantic_manifest = {
            str(name): value
            for name, value in manifest.items()
            if str(name) not in _TRANSPORT_FIELDS
        }
    canonical_checksums = {str(name): str(value) for name, value in artifact_checksums.items()}
    if not canonical_checksums:
        raise ValueError("dataset identity requires a non-empty artifact checksum index")
    return {
        "identity_version": DATASET_IDENTITY_VERSION,
        "manifest": semantic_manifest,
        "artifacts": canonical_checksums,
    }


def dataset_processed_checksum(
    manifest: DatasetManifest | Mapping[str, Any],
    artifact_checksums: Mapping[str, str],
) -> str:
    """Compute the canonical, prefixed semantic identity for a prepared dataset."""

    return f"sha256:{sha256_value(dataset_identity_payload(manifest, artifact_checksums))}"


__all__ = [
    "DATASET_IDENTITY_VERSION",
    "dataset_identity_payload",
    "dataset_processed_checksum",
]
