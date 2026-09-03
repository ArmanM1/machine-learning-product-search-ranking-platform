"""Immutable public-release pointer contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr

ReleaseId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$", min_length=3, max_length=100),
]
ModelId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,99}$", min_length=3, max_length=100),
]
GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$", min_length=7, max_length=64)]


class PreviousReleasePointer(ContractModel):
    """Rollback identity captured before the current pointer was advanced."""

    release_id: ReleaseId
    model_id: ModelId
    pointer_version_id: NonEmptyStr


class PromotionPointer(ContractModel):
    """Select one immutable public bundle while naming the actually active model.

    A held-out failure is a new public evidence release, not a model promotion. In
    that case the pointer advances to a release-specific bundle but retains the
    exact prior baseline model ID.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    release_id: ReleaseId
    model_id: ModelId
    bundle_s3_key: NonEmptyStr
    evaluation_report_id: NonEmptyStr
    git_sha: GitSha
    evidence_mode: Literal["validation_only", "verified"]
    release_decision: Literal["validation_baseline", "promote_candidate", "retain_baseline"]
    gate_passed: bool | None
    evaluated_candidate_model_id: ModelId | None
    previous: PreviousReleasePointer | None

    @model_validator(mode="after")
    def decision_matches_active_model_and_immutable_bundle(self) -> PromotionPointer:
        if self.evidence_mode == "validation_only":
            if self.release_decision != "validation_baseline":
                raise ValueError("validation-only pointers require validation_baseline")
            if self.gate_passed is not None or self.evaluated_candidate_model_id is not None:
                raise ValueError("validation-only pointers cannot record a held-out gate")
            if self.previous is not None:
                raise ValueError("the initial validation baseline cannot name a previous release")
            expected_key = f"promoted/{self.model_id}/"
        else:
            if self.gate_passed is None or self.evaluated_candidate_model_id is None:
                raise ValueError("verified pointers require the held-out decision and candidate")
            if self.previous is None:
                raise ValueError("verified releases require a rollback-safe previous pointer")
            expected_key = f"promoted/releases/{self.release_id}/"
            if self.gate_passed:
                if self.release_decision != "promote_candidate":
                    raise ValueError("a passed gate must record promote_candidate")
                if self.model_id != self.evaluated_candidate_model_id:
                    raise ValueError("a passed gate must activate the evaluated candidate")
            else:
                if self.release_decision != "retain_baseline":
                    raise ValueError("a failed gate must record retain_baseline")
                if self.model_id == self.evaluated_candidate_model_id:
                    raise ValueError("a failed gate cannot activate the evaluated candidate")
                if self.previous.model_id != self.model_id:
                    raise ValueError("a failed gate must retain the previously active baseline")
        if self.bundle_s3_key != expected_key:
            raise ValueError(f"bundle_s3_key must be the immutable canonical key {expected_key}")
        return self


__all__ = ["PreviousReleasePointer", "PromotionPointer"]
