"""Configuration loading, validation, and canonical hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"configuration file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"configuration root must be an object: {config_path}")
    return value


def validate_config(path: str | Path, model: type[ModelT]) -> ModelT:
    return model.model_validate(load_yaml(path))


def canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def config_hash_without_field(value: dict[str, Any], field: str = "config_hash") -> str:
    canonical = dict(value)
    canonical.pop(field, None)
    return sha256_value(canonical)


def assert_embedded_hash(value: dict[str, Any], field: str = "config_hash") -> str:
    expected = value.get(field)
    actual = config_hash_without_field(value, field)
    if expected not in {actual, f"sha256:{actual}"}:
        raise ValueError(f"{field} mismatch: expected canonical SHA-256 {actual}")
    return actual
