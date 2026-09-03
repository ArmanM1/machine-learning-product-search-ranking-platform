from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from search_rank.artifacts.checksums import sha256_file, verify_file
from search_rank.config import canonical_json, config_hash_without_field, sha256_value
from search_rank.training.configuration import load_frozen_experiment

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_DATASET_HASH = "sha256:814e06ceba032871d1cac66cd4dd59177f4348c9928fdf417f2a2f3218a29525"
FROZEN_CANDIDATE_HASHES = {
    "candidate-v1.yaml": "sha256:10646da48afd7bcf255233331919017b4e76ea132f4bbc149ef4a5102f7c2767",
    "candidate-random-ablation-v1.yaml": (
        "sha256:960911ea788a47d16a5ec0f14d820c2c4bdd6f387d0224aaa740dc49071cc133"
    ),
    "candidate-title-ablation-v1.yaml": (
        "sha256:597ea69bcfc9dea3db3a817d29a7ee550cfc20fcf4d3bcc688a0295b1dd0f071"
    ),
}


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    assert sha256_value({"b": 2, "a": 1}) == sha256_value({"a": 1, "b": 2})


def test_config_hash_excludes_embedded_hash() -> None:
    expected = sha256_value({"name": "candidate"})
    assert config_hash_without_field({"name": "candidate", "config_hash": "ignored"}) == expected


@pytest.mark.parametrize(("filename", "expected_hash"), FROZEN_CANDIDATE_HASHES.items())
def test_frozen_candidates_bind_the_published_dataset_and_exact_json_mirror(
    filename: str,
    expected_hash: str,
) -> None:
    path = ROOT / "configs" / "experiments" / filename
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = load_frozen_experiment(path)
    sidecar = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))

    assert raw["dataset_manifest_hash"] == PUBLISHED_DATASET_HASH
    assert config.dataset_manifest_hash == PUBLISHED_DATASET_HASH
    assert config.config_hash == expected_hash
    assert "sha256:" + config_hash_without_field(raw) == expected_hash
    assert sidecar == config.model_dump(mode="json")


def test_file_checksum_verification(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"immutable")
    expected = hashlib.sha256(b"immutable").hexdigest()
    assert sha256_file(path) == expected
    assert verify_file(path, f"sha256:{expected}") == expected
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_file(path, "0" * 64)
