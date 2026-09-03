"""Dataset manifest contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from search_rank.config import sha256_value

from .common import ContractModel, NonEmptyStr, SchemaVersion, Sha256, UtcDateTime

Count = Annotated[int, Field(ge=0)]


class SplitCounts(ContractModel):
    """Auditable counts for one query-isolated split."""

    query_count: Count
    row_count: Count
    product_count: Count

    @model_validator(mode="after")
    def counts_fit_the_split_rows(self) -> SplitCounts:
        if self.query_count > self.row_count:
            raise ValueError("split query_count cannot exceed row_count")
        if self.product_count > self.row_count:
            raise ValueError("split product_count cannot exceed row_count")
        return self


class SplitManifestIdentity(ContractModel):
    """Canonical identity of the query-isolated split assignment and its source."""

    identity_version: Literal["query-split-manifest-v1"] = "query-split-manifest-v1"
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    source_revision: NonEmptyStr
    locale: NonEmptyStr
    raw_checksums: dict[NonEmptyStr, Sha256] = Field(min_length=1)
    preprocessing_version: NonEmptyStr
    split_strategy: NonEmptyStr
    split_salt_hash: Sha256
    split_counts: dict[NonEmptyStr, SplitCounts]
    split_query_id_hashes: dict[NonEmptyStr, Sha256]
    row_count: Count
    query_count: Count

    def checksum(self) -> str:
        return f"sha256:{sha256_value(self.model_dump(mode='json'))}"


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
    split_manifest_hash: Sha256
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
        if self.row_count != sum(split.row_count for split in self.split_counts.values()):
            raise ValueError("row_count must equal the sum of train/validation/test rows")
        if self.query_count != sum(split.query_count for split in self.split_counts.values()):
            raise ValueError(
                "query_count must equal the sum of query-isolated train/validation/test queries"
            )
        if self.product_count > self.row_count:
            raise ValueError("product_count cannot exceed row_count")
        split_identity = SplitManifestIdentity(
            dataset_name=self.dataset_name,
            dataset_version=self.dataset_version,
            source_revision=self.source_revision,
            locale=self.locale,
            raw_checksums=self.raw_checksums,
            preprocessing_version=self.preprocessing_version,
            split_strategy=self.split_strategy,
            split_salt_hash=self.split_salt_hash,
            split_counts=self.split_counts,
            split_query_id_hashes=self.split_query_id_hashes,
            row_count=self.row_count,
            query_count=self.query_count,
        )
        if self.split_manifest_hash != split_identity.checksum():
            raise ValueError("split_manifest_hash does not match the canonical split identity")
        return self


SplitCount = SplitCounts

__all__ = ["DatasetManifest", "SplitCount", "SplitCounts", "SplitManifestIdentity"]
