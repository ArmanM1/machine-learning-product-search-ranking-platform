from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from search_rank.artifacts.checksums import sha256_file, verify_file
from search_rank.config import canonical_json, config_hash_without_field, sha256_value


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    assert sha256_value({"b": 2, "a": 1}) == sha256_value({"a": 1, "b": 2})


def test_config_hash_excludes_embedded_hash() -> None:
    expected = sha256_value({"name": "candidate"})
    assert config_hash_without_field({"name": "candidate", "config_hash": "ignored"}) == expected


def test_file_checksum_verification(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"immutable")
    expected = hashlib.sha256(b"immutable").hexdigest()
    assert sha256_file(path) == expected
    assert verify_file(path, f"sha256:{expected}") == expected
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_file(path, "0" * 64)
