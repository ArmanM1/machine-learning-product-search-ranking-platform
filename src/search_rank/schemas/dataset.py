"""Dataset manifest contract."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, SchemaVersion, Sha256, UtcDateTime

Count = Annotated[int, Field(ge=0)]


class SplitCounts(ContractModel):
    """Auditable counts for one query-isolated split."""

    query_count: Count
    row_count: Count
    product_count: Count


class DatasetManifest(ContractModel):
    """Immutable description of a prepared dataset release."""

    schema_version: SchemaVersion
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    source_url: NonEmptyStr
    source_revision: NonEmptyStr
    license_url: NonEmptyStr
    license_notice_hash: Sha256
    task: NonEmptyStr
    locale: NonEmptyStr
    raw_checksums: dict[NonEmptyStr, Sha256] = Field(min_length=1)
    preprocessing_version: NonEmptyStr
    split_strategy: NonEmptyStr
    split_salt_hash: Sha256
    split_counts: dict[NonEmptyStr, SplitCounts]
    split_query_id_hashes: dict[NonEmptyStr, Sha256]
    row_count: Count
    query_count: Count
    product_count: Count
    label_distribution: dict[NonEmptyStr, Count]
    missingness: dict[NonEmptyStr, Count]
    dropped_rows: dict[NonEmptyStr, Count]
    processed_artifact_uri: NonEmptyStr
    processed_checksum: Sha256
    created_at: UtcDateTime

    @model_validator(mode="after")
    def required_split_evidence_is_complete(self) -> DatasetManifest:
        required = {"train", "validation", "test"}
        missing_counts = required - set(self.split_counts)
        missing_hashes = required - set(self.split_query_id_hashes)
        if missing_counts or missing_hashes:
            raise ValueError(
                "dataset manifest requires train/validation/test counts and query-ID hashes; "
                f"missing_counts={sorted(missing_counts)}, missing_hashes={sorted(missing_hashes)}"
            )
        if set(self.split_counts) != set(self.split_query_id_hashes):
            raise ValueError(
                "split_counts and split_query_id_hashes must use identical split names"
            )
        return self


SplitCount = SplitCounts

__all__ = ["DatasetManifest", "SplitCount", "SplitCounts"]
