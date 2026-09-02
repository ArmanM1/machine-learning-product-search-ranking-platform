"""Fail-closed redaction for evidence copied to public surfaces."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

_DENIED_KEYS = frozenset(
    {
        "account",
        "account_id",
        "aws_account_id",
        "bucket",
        "bucket_name",
        "cloud_project_alias",
        "credential",
        "credentials",
        "secret",
        "secret_access_key",
        "session_token",
        "password",
        "token",
        "signed_url",
        "presigned_url",
        "artifact_uri",
        "artifact_uris",
        "checkpoint_uri",
        "image_uri",
        "internal_path",
    }
)
_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "credential",
    "signed_url",
    "presigned",
    "bucket",
    "access_key",
    "api_key",
)
_ARN_ACCOUNT = re.compile(r"(arn:(?:aws|aws-us-gov|aws-cn):[^:]*:[^:]*:)(\d{12})(:)")
_AWS_ACCOUNT_CONTEXT = re.compile(
    r"(\b(?:aws[ _-]?)?account(?:[ _-]?id)?\s*[=:]\s*)\d{12}\b",
    re.IGNORECASE,
)
_BARE_AWS_ACCOUNT = re.compile(r"^\d{12}$")
_S3_URI = re.compile(r"s3://[^\s/]+(?:/[^\s]*)?", re.IGNORECASE)
_SIGNED_QUERY = re.compile(
    r"https?://[^\s]+[?&](?:X-Amz-(?:Signature|Credential|Security-Token)|Signature)=",
    re.IGNORECASE,
)


def _key_is_sensitive(key: object) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    token_key = (
        normalized == "token" or normalized.startswith("token_") or normalized.endswith("_token")
    )
    account_key = normalized == "account" or "account_id" in normalized
    return (
        normalized in _DENIED_KEYS
        or token_key
        or account_key
        or any(part in normalized for part in _SENSITIVE_KEY_PARTS)
    )


def _redact_string(value: str) -> str:
    if _SIGNED_QUERY.search(value):
        return "<redacted-signed-url>"
    if _S3_URI.search(value):
        return _S3_URI.sub("<redacted-s3-uri>", value)
    value = _ARN_ACCOUNT.sub(r"\1<redacted-account>\3", value)
    if _BARE_AWS_ACCOUNT.fullmatch(value):
        return "<redacted-account>"
    return _AWS_ACCOUNT_CONTEXT.sub(r"\1<redacted-account>", value)


def redact_public(value: Any) -> Any:
    """Return a recursively sanitized, JSON-compatible public copy.

    Sensitive fields are removed rather than replaced so downstream clients do
    not mistake redaction markers for usable locations or credentials.
    """

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): redact_public(item)
            for key, item in value.items()
            if not _key_is_sensitive(key)
        }
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact_public(item) for item in value]
    return value


# Descriptive alias used at API/report call sites.
redact_for_public = redact_public

__all__ = ["redact_for_public", "redact_public"]
