"""Shared, strict types for versioned artifact and API contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints


def _as_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalize aware values to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(UTC)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SchemaVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]


class ContractModel(BaseModel):
    """Base model used by every persisted or public contract.

    Unknown fields are rejected so misspelled evidence fields cannot silently
    disappear, and assignment remains validated while reports are assembled.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )


__all__ = [
    "ContractModel",
    "NonEmptyStr",
    "SchemaVersion",
    "Sha256",
    "UtcDateTime",
]
