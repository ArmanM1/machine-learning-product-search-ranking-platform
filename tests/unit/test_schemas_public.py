from __future__ import annotations

from search_rank.schemas.public import redact_for_public


def test_public_redaction_removes_private_locations_and_credentials_recursively() -> None:
    internal = {
        "run_id": "run-1",
        "aws_account_id": "123456789012",
        "artifact_uris": {"model": "s3://private-bucket/model.tar.gz"},
        "nested": {
            "checkpoint_uri": "s3://secret/checkpoint",
            "password": "do-not-leak",
            "safe_hash": "sha256:" + "a" * 64,
        },
    }
    public = redact_for_public(internal)
    assert public == {
        "run_id": "run-1",
        "nested": {"safe_hash": "sha256:" + "a" * 64},
    }


def test_public_redaction_masks_account_ids_arns_s3_and_presigned_urls_in_text() -> None:
    public = redact_for_public(
        {
            "message": "arn:aws:iam::123456789012:role/example",
            "path_in_message": "loaded s3://private-bucket/a/b",
            "link": "https://bucket.s3.amazonaws.com/a?X-Amz-Signature=abc",
        }
    )
    assert "123456789012" not in public["message"]
    assert "private-bucket" not in public["path_in_message"]
    assert public["link"] == "<redacted-signed-url>"


def test_redaction_does_not_corrupt_content_addressed_hashes() -> None:
    digest = "sha256:abc123456789012def" + "0" * 46
    assert redact_for_public({"artifact_checksum": digest}) == {"artifact_checksum": digest}
