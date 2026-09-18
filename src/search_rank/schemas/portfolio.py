"""Strict, public-safe contracts for durable portfolio release evidence."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .api import (
    PublicEvaluationProvenance,
    PublicFailureExample,
    PublicMetricComparison,
    PublicModelMetricRow,
    PublicSliceResult,
)
from .common import ContractModel, NonEmptyStr, Sha256, UtcDateTime
from .evaluation import PairedDifference

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
FullGitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PublicIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,127}$", min_length=3, max_length=128),
]
CloudFrontOrigin = Annotated[
    str,
    Field(pattern=r"^https://[a-z0-9-]+\.cloudfront\.net$"),
]
TrialSelectionId = Annotated[str, Field(pattern=r"^trial-selection-[0-9a-f]{20}$")]


class PortfolioAblationTrial(ContractModel):
    """Allowlisted validation result for one preregistered treatment or control."""

    role: Literal[
        "candidate_treatment",
        "random_negative_control",
        "title_only_control",
    ]
    promotion_eligible: bool
    model_id: PublicIdentifier
    config_id: PublicIdentifier
    config_sha256: Sha256
    input_template_version: Literal["title_v1", "enriched_v1"]
    sampling_strategy: Literal["mixed_hard_random_v1", "random_only_v1"]
    hard_example_sources: list[Literal["bm25", "pretrained_cross_encoder"]]
    validation_graded_ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class PortfolioAblationContrast(ContractModel):
    """Allowlisted result for one mandatory single-factor validation contrast."""

    contrast_id: Literal["mixed_vs_random_sampling", "enriched_vs_title_input"]
    control_role: Literal["random_negative_control", "title_only_control"]
    controlled_difference_fields: list[NonEmptyStr]
    treatment_validation_graded_ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    control_validation_graded_ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    treatment_minus_control: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]


class PortfolioAblationEvidence(ContractModel):
    """Sanitized and checksum-bound projection of the frozen trial selection."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["portfolio_ablation_evidence"]
    source_trial_selection_sha256: Sha256
    selection_id: TrialSelectionId
    git_sha: FullGitSha
    dataset_manifest_sha256: Sha256
    metric: Literal["graded_ndcg@10"]
    test_access_count: Literal[0]
    selected_model_id: PublicIdentifier
    selected_config_sha256: Sha256
    trials: Annotated[list[PortfolioAblationTrial], Field(min_length=3, max_length=3)]
    contrasts: Annotated[list[PortfolioAblationContrast], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def ablations_are_complete_and_bound(self) -> PortfolioAblationEvidence:
        by_role: dict[str, PortfolioAblationTrial] = {trial.role: trial for trial in self.trials}
        required_roles = {
            "candidate_treatment",
            "random_negative_control",
            "title_only_control",
        }
        if set(by_role) != required_roles or len(by_role) != len(self.trials):
            raise ValueError("portfolio ablations must contain each mandatory role exactly once")
        treatment = by_role["candidate_treatment"]
        if not treatment.promotion_eligible or any(
            trial.promotion_eligible
            for role, trial in by_role.items()
            if role != "candidate_treatment"
        ):
            raise ValueError("only the preregistered treatment may be promotion eligible")
        if (
            self.selected_model_id != treatment.model_id
            or self.selected_config_sha256 != treatment.config_sha256
        ):
            raise ValueError("selected candidate differs from the portfolio treatment")

        by_contrast: dict[str, PortfolioAblationContrast] = {
            contrast.contrast_id: contrast for contrast in self.contrasts
        }
        expected = {
            "mixed_vs_random_sampling": "random_negative_control",
            "enriched_vs_title_input": "title_only_control",
        }
        if set(by_contrast) != set(expected) or len(by_contrast) != len(self.contrasts):
            raise ValueError("portfolio evidence requires both mandatory contrasts exactly once")
        for contrast_id, control_role in expected.items():
            contrast = by_contrast[contrast_id]
            control = by_role[control_role]
            delta = treatment.validation_graded_ndcg_at_10 - control.validation_graded_ndcg_at_10
            if contrast.control_role != control_role or not (
                math.isclose(
                    contrast.treatment_validation_graded_ndcg_at_10,
                    treatment.validation_graded_ndcg_at_10,
                    rel_tol=0,
                    abs_tol=1e-15,
                )
                and math.isclose(
                    contrast.control_validation_graded_ndcg_at_10,
                    control.validation_graded_ndcg_at_10,
                    rel_tol=0,
                    abs_tol=1e-15,
                )
                and math.isclose(
                    contrast.treatment_minus_control,
                    delta,
                    rel_tol=0,
                    abs_tol=1e-15,
                )
            ):
                raise ValueError(f"{contrast_id} differs from its sanitized trial values")
        return self


class PortfolioSelectedReleaseModel(ContractModel):
    model_id: PublicIdentifier
    artifact_sha256: Sha256


class PortfolioEvaluatedCandidate(ContractModel):
    model_id: PublicIdentifier
    artifact_sha256: Sha256
    config_sha256: Sha256
    base_model_id: NonEmptyStr
    base_model_revision: NonEmptyStr
    training_strategy: NonEmptyStr


class PortfolioTrainingProvenance(ContractModel):
    """Allowlisted training provenance with private workflow/job identity removed."""

    trial_selection_id: TrialSelectionId
    trial_selection_sha256: Sha256
    run_manifest_sha256: Sha256
    selected_model_id: PublicIdentifier
    selected_model_artifact_checksum: Sha256
    config_hash: Sha256
    git_sha: FullGitSha
    image_digest: Sha256
    hardware_class: Literal["ml.m5.xlarge", "ml.g4dn.xlarge"]
    accelerator: Literal["cpu", "gpu"]
    region: Literal["us-east-1"]
    runtime_seconds: NonNegativeFloat
    estimated_cost_usd: NonNegativeFloat
    actual_cost_usd: NonNegativeFloat | None = None
    cost_evidence: NonEmptyStr

    @model_validator(mode="after")
    def hardware_matches_accelerator(self) -> PortfolioTrainingProvenance:
        if self.hardware_class.endswith("g4dn.xlarge") != (self.accelerator == "gpu"):
            raise ValueError("portfolio training hardware and accelerator do not match")
        return self


class PortfolioPublicEvidence(ContractModel):
    """Durable allowlist copied from the typed public evidence served by the release."""

    source_public_evidence_sha256: Sha256
    dataset_name: NonEmptyStr
    dataset_version: NonEmptyStr
    locale: Literal["us"]
    selected_release_model: PortfolioSelectedReleaseModel
    evaluated_candidate: PortfolioEvaluatedCandidate
    training_provenance: PortfolioTrainingProvenance
    evaluation_provenance: PublicEvaluationProvenance
    held_out_test_access_count: Annotated[int, Field(ge=1)]
    model_metrics: Annotated[list[PublicModelMetricRow], Field(min_length=2)]
    secondary_metrics: list[PublicMetricComparison]
    ablations: PortfolioAblationEvidence
    slices: list[PublicSliceResult]
    examples: Annotated[list[PublicFailureExample], Field(min_length=15)]
    limitations: list[NonEmptyStr]
    prohibited_claims: list[NonEmptyStr]

    @model_validator(mode="after")
    def public_snapshot_is_internally_bound(self) -> PortfolioPublicEvidence:
        training = self.training_provenance
        evaluation = self.evaluation_provenance
        candidate = self.evaluated_candidate
        if (
            training.selected_model_id != candidate.model_id
            or training.selected_model_artifact_checksum != candidate.artifact_sha256
            or training.config_hash != candidate.config_sha256
            or evaluation.candidate_model_id != candidate.model_id
            or evaluation.candidate_model_artifact_checksum != candidate.artifact_sha256
        ):
            raise ValueError("durable candidate identity differs from execution provenance")
        if (
            self.ablations.selection_id != training.trial_selection_id
            or self.ablations.source_trial_selection_sha256 != training.trial_selection_sha256
            or self.ablations.git_sha != training.git_sha
            or self.ablations.selected_model_id != candidate.model_id
            or self.ablations.selected_config_sha256 != candidate.config_sha256
        ):
            raise ValueError("durable ablations differ from selected training provenance")
        model_ids = [row.model_id for row in self.model_metrics]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("durable model metrics must use unique model IDs")
        if (
            candidate.model_id not in model_ids
            or self.selected_release_model.model_id not in model_ids
        ):
            raise ValueError("durable model metrics omit a release model")
        return self


class PortfolioReleaseIdentities(ContractModel):
    release_git_sha: FullGitSha
    deployment_git_sha: FullGitSha
    dataset_manifest_sha256: Sha256
    model_artifact_sha256: Sha256
    evaluation_image_digest: Sha256
    serving_image_digest: Sha256
    trial_selection_id: TrialSelectionId
    trial_selection_sha256: Sha256


class PortfolioReleaseGate(ContractModel):
    passed: bool
    decision: Literal["promote_candidate", "retain_baseline"]
    promoted_model_id: PublicIdentifier
    evaluated_candidate_model_id: PublicIdentifier
    strongest_baseline_model_id: PublicIdentifier

    @model_validator(mode="after")
    def decision_is_consistent(self) -> PortfolioReleaseGate:
        expected = (
            self.evaluated_candidate_model_id if self.passed else self.strongest_baseline_model_id
        )
        if self.promoted_model_id != expected:
            raise ValueError("portfolio release gate promotes the wrong model")
        if self.decision != ("promote_candidate" if self.passed else "retain_baseline"):
            raise ValueError("portfolio release gate decision differs from its outcome")
        return self


class PortfolioMetrics(ContractModel):
    primary_metric: Literal["graded_ndcg@10"]
    candidate_value: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    strongest_baseline_value: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    candidate_minus_baseline: FiniteFloat
    paired_differences: Annotated[list[PairedDifference], Field(min_length=1)]

    @model_validator(mode="after")
    def primary_difference_is_exact(self) -> PortfolioMetrics:
        if (
            abs(
                self.candidate_value - self.strongest_baseline_value - self.candidate_minus_baseline
            )
            > 1e-9
        ):
            raise ValueError("portfolio primary difference is inconsistent")
        return self


class PortfolioDeployment(ContractModel):
    public_url: CloudFrontOrigin
    smoke_tests_passed: Literal[True]
    candidate_gate_error_rate: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    candidate_gate_p95_ms: NonNegativeFloat
    controlled_cold_start_ms: NonNegativeFloat


class PortfolioLatencySummary(ContractModel):
    p50: NonNegativeFloat
    p95: NonNegativeFloat
    p99: NonNegativeFloat
    mean: NonNegativeFloat
    minimum: NonNegativeFloat
    maximum: NonNegativeFloat

    @model_validator(mode="after")
    def values_are_ordered(self) -> PortfolioLatencySummary:
        if not self.minimum <= self.p50 <= self.p95 <= self.p99 <= self.maximum:
            raise ValueError("portfolio latency percentiles are not monotonic")
        if not self.minimum <= self.mean <= self.maximum:
            raise ValueError("portfolio latency mean is outside its observed bounds")
        return self


class PortfolioBenchmark(ContractModel):
    protocol: Literal["warm_after_explicit_per_condition_warmups"]
    primary_candidate_count: Literal[40]
    primary_offered_concurrency: Literal[1]
    measured_request_count: Literal[1800]
    measured_success_count: Count
    measured_error_count: Count
    measured_throttle_count: Count
    primary_end_to_end_latency_ms: PortfolioLatencySummary
    primary_model_latency_ms: PortfolioLatencySummary
    primary_serialization_latency_ms: PortfolioLatencySummary
    controlled_cold_start_ms: NonNegativeFloat
    controlled_cold_init_ms: NonNegativeFloat
    controlled_cold_max_memory_mb: NonNegativeFloat
    latency_claim: NonEmptyStr
    throughput_claim_eligible: Literal[False]
    scaling_claim_eligible: Literal[False]
    limitations: Annotated[list[NonEmptyStr], Field(min_length=5)]

    @model_validator(mode="after")
    def request_totals_are_consistent(self) -> PortfolioBenchmark:
        if self.measured_success_count + self.measured_error_count != self.measured_request_count:
            raise ValueError("portfolio benchmark request totals are inconsistent")
        if self.measured_throttle_count > self.measured_error_count:
            raise ValueError("portfolio benchmark throttles exceed its errors")
        return self


class PortfolioRollback(ContractModel):
    verified: Literal[True]
    restored_model_id: PublicIdentifier
    smoke_tests_passed: Literal[True]


class PortfolioRedeployment(ContractModel):
    verified: Literal[True]
    release_id: PublicIdentifier
    model_id: PublicIdentifier
    exact_winner_redeployed: Literal[True]
    fresh_runtime_revision_published: Literal[True]
    public_url: CloudFrontOrigin


class PortfolioClaimBoundaries(ContractModel):
    held_out_positive_claim_allowed: bool
    negative_result_required: bool
    throughput_claim_eligible: Literal[False]
    scaling_claim_eligible: Literal[False]
    limitations: list[NonEmptyStr]
    prohibited_claims: list[NonEmptyStr]

    @model_validator(mode="after")
    def positive_and_negative_claims_are_complements(self) -> PortfolioClaimBoundaries:
        if self.held_out_positive_claim_allowed == self.negative_result_required:
            raise ValueError("positive and negative portfolio claim states must be complements")
        return self


class PortfolioArtifactChecksums(ContractModel):
    release_manifest: Sha256
    public_evidence: Sha256
    bundle_checksums: Sha256
    heldout_evaluation_report: Sha256
    heldout_evaluation_provenance: Sha256
    public_ablation_evidence: Sha256
    baseline_deployment_evidence: Sha256
    deployment_evidence: Sha256
    promotion_pointer: Sha256
    benchmark_performance_report: Sha256
    benchmark_evidence_checksums: Sha256
    rollback_evidence: Sha256
    redeployment_evidence: Sha256


class PortfolioReleaseEvidence(ContractModel):
    """One immutable, resume-safe release record assembled from the full evidence chain."""

    schema_version: Literal["1.0.0"]
    evidence_status: Literal["verified_measurement"]
    generated_at: UtcDateTime
    public_demo_expires_at: UtcDateTime
    evidence_mode: Literal["verified"]
    release_id: PublicIdentifier
    identities: PortfolioReleaseIdentities
    release_gate: PortfolioReleaseGate
    metrics: PortfolioMetrics
    public_evidence: PortfolioPublicEvidence
    deployment: PortfolioDeployment
    benchmark: PortfolioBenchmark
    rollback: PortfolioRollback
    redeployment: PortfolioRedeployment
    claim_boundaries: PortfolioClaimBoundaries
    artifact_sha256: PortfolioArtifactChecksums

    @model_validator(mode="after")
    def complete_record_is_cross_bound(self) -> PortfolioReleaseEvidence:
        public = self.public_evidence
        gate = self.release_gate
        identities = self.identities
        lifetime_seconds = (self.public_demo_expires_at - self.generated_at).total_seconds()
        if not 0 < lifetime_seconds <= 24 * 60 * 60:
            raise ValueError("portfolio release evidence must precede public demo expiry")
        if (
            self.release_id != self.redeployment.release_id
            or gate.promoted_model_id != self.redeployment.model_id
            or gate.promoted_model_id != public.selected_release_model.model_id
        ):
            raise ValueError("portfolio release identities differ across deployment evidence")
        if self.deployment.public_url != self.redeployment.public_url:
            raise ValueError("portfolio deployment origins differ")
        if (
            identities.release_git_sha != public.training_provenance.git_sha
            or identities.release_git_sha != public.evaluation_provenance.git_sha
            or identities.dataset_manifest_sha256 != public.ablations.dataset_manifest_sha256
            or identities.model_artifact_sha256 != public.selected_release_model.artifact_sha256
            or identities.trial_selection_id != public.ablations.selection_id
            or identities.trial_selection_sha256 != public.ablations.source_trial_selection_sha256
        ):
            raise ValueError("portfolio public evidence differs from release identities")
        if (
            gate.evaluated_candidate_model_id != public.evaluated_candidate.model_id
            or gate.strongest_baseline_model_id
            not in {row.model_id for row in public.model_metrics}
        ):
            raise ValueError("portfolio public evidence differs from the release gate")
        by_model = {row.model_id: row for row in public.model_metrics}
        candidate = by_model[gate.evaluated_candidate_model_id]
        baseline = by_model[gate.strongest_baseline_model_id]
        if not (
            math.isclose(
                candidate.graded_ndcg_at_10,
                self.metrics.candidate_value,
                rel_tol=0,
                abs_tol=1e-9,
            )
            and math.isclose(
                baseline.graded_ndcg_at_10,
                self.metrics.strongest_baseline_value,
                rel_tol=0,
                abs_tol=1e-9,
            )
        ):
            raise ValueError("portfolio model rows differ from held-out metrics")
        if self.artifact_sha256.public_evidence != public.source_public_evidence_sha256:
            raise ValueError("portfolio public-evidence checksum differs from its source")
        claims = self.claim_boundaries
        if (
            claims.held_out_positive_claim_allowed != gate.passed
            or claims.negative_result_required == gate.passed
            or claims.throughput_claim_eligible != self.benchmark.throughput_claim_eligible
            or claims.scaling_claim_eligible != self.benchmark.scaling_claim_eligible
            or claims.limitations != public.limitations
            or claims.prohibited_claims != public.prohibited_claims
        ):
            raise ValueError("portfolio claim boundaries differ from measured evidence")
        return self


__all__ = [
    "PortfolioAblationContrast",
    "PortfolioAblationEvidence",
    "PortfolioAblationTrial",
    "PortfolioReleaseEvidence",
]
