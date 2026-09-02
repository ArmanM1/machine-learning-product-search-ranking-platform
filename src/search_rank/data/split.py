"""Query-isolated deterministic validation and development splits."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


def query_hash(query_id: str | int, salt: str) -> int:
    payload = f"{salt}\0{query_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def assign_train_validation(
    query_id: str | int,
    *,
    validation_fraction: float,
    salt: str,
) -> str:
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    bucket = query_hash(query_id, salt) / 2**64
    return "validation" if bucket < validation_fraction else "train"


def development_query_ids(query_ids: Iterable[str | int], *, count: int, salt: str) -> set[str]:
    if count < 1:
        raise ValueError("development query count must be positive")
    unique = {str(value) for value in query_ids}
    ordered = sorted(unique, key=lambda value: (query_hash(value, salt), value))
    return set(ordered[:count])


def sorted_id_hash(query_ids: Iterable[str | int]) -> str:
    canonical = "\n".join(sorted({str(value) for value in query_ids})).encode()
    return hashlib.sha256(canonical).hexdigest()
