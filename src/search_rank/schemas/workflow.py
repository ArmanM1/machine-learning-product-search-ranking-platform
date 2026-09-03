"""Strict contracts for durable JSON evidence emitted by cloud workflows."""

from __future__ import annotations

import math
import statistics
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, Sha256, UtcDateTime
from .performance import ColdStartEvidence

RawSha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FullGitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
LambdaVersion = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
CloudFrontOrigin = Annotated[
    str,
    Field(pattern=r"^https://[a-z0-9-]+\.cloudfront\.net$", max_length=253),
]
TrainingImageUri = Annotated[
    str,
    Field(
        pattern=(
            r"^[0-9]{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/"
            r"[a-z0-9/_-]+@sha256:[0-9a-f]{64}$"
        )
    ),
]


class TrainingImageProvenance(ContractModel):
    schema_version: Literal["1.0.0"]
    git_sha: FullGitSha
    repository_dirty: Literal[False]
    source_tag: Annotated[str, Field(pattern=r"^sha-[0-9a-f]{40}$")]
    image_uri: TrainingImageUri
    image_digest: Sha256
    binding_verified: Literal[True]

    @model_validator(mode="after")
    def source_and_digest_are_exact(self) -> TrainingImageProvenance:
        if self.source_tag != "sha-" + self.git_sha:
            raise ValueError("training image source tag and Git SHA differ")
        if not self.image_uri.endswith("@" + self.image_digest):
            raise ValueError("training image URI and digest differ")
        return self


class CloudTrainingJobEvidence(ContractModel):
    training_job_name: Annotated[str, Field(pattern=r"^product-search-ranking-prod-[a-z]+-[0-9]+$")]
    status: Literal["Completed"]
    instance_type: Literal["ml.m5.xlarge", "ml.g4dn.xlarge"]
    instance_count: Literal[1]
    accelerator: Literal["cpu", "gpu"]
    config_role: Literal["candidate_treatment", "random_negative_control", "title_only_control"]
    run_kind: Literal["development", "ablation", "final"]
    region: Literal["us-east-1"]
    managed_spot: Literal[True]
    training_seconds: Annotated[int, Field(ge=0)]
    billable_seconds: Annotated[int, Field(ge=0)]
    creation_time: UtcDateTime
    training_start_time: UtcDateTime
    end_time: UtcDateTime
    git_sha: FullGitSha
    repository_dirty: Literal[False]
    dataset_manifest_hash: Sha256
    config_file_sha256: RawSha256
    image_uri: TrainingImageUri
    image_digest: Sha256
    image_source_tag: Annotated[str, Field(pattern=r"^sha-[0-9a-f]{40}$")]
    output_key_prefix: Annotated[str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+/$")]
    model_artifact_key: Annotated[str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+\.tar\.gz$")]

    @model_validator(mode="after")
    def runtime_identity_is_consistent(self) -> CloudTrainingJobEvidence:
        if self.instance_type.endswith("g4dn.xlarge") != (self.accelerator == "gpu"):
            raise ValueError("training instance and declared accelerator differ")
        if self.image_source_tag != "sha-" + self.git_sha:
            raise ValueError("training image source tag and Git SHA differ")
        if not self.image_uri.endswith("@" + self.image_digest):
            raise ValueError("training image URI and digest differ")
        if not self.output_key_prefix.startswith(f"runs/{self.training_job_name}/"):
            raise ValueError("training output prefix differs from the job identity")
        if not self.model_artifact_key.startswith(self.output_key_prefix):
            raise ValueError("training model artifact is outside the job output")
        if not self.creation_time <= self.training_start_time <= self.end_time:
            raise ValueError("training job timestamps are not ordered")
        if self.billable_seconds > self.training_seconds:
            raise ValueError("managed-spot billable time exceeds training time")
        return self


class CandidateReleaseInputs(ContractModel):
    """Release-facing identity emitted after a successful cloud training job."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["candidate_release_inputs"]
    candidate_run_id: NonEmptyStr
    candidate_model_id: NonEmptyStr
    candidate_artifact_s3_key: Annotated[str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+\.tar\.gz$")]
    candidate_artifact_sha256: RawSha256
    candidate_checkpoint_sha256: RawSha256
    candidate_training_config_sha256: Sha256
    candidate_training_config_path: Annotated[
        str, Field(pattern=r"^configs/experiments/[A-Za-z0-9._/-]+\.ya?ml$")
    ]
    candidate_training_config_s3_key: Annotated[
        str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+/config/experiment\.yaml$")
    ]
    candidate_training_config_file_sha256: RawSha256
    dataset_manifest_hash: Sha256
    best_validation_ndcg_at_10: UnitFloat
    training_run_kind: Literal["development", "ablation", "final"]
    training_config_role: Literal[
        "candidate_treatment", "random_negative_control", "title_only_control"
    ]
    git_sha: FullGitSha
    repository_dirty: Literal[False]
    training_image_uri: Annotated[
        str,
        Field(
            pattern=(
                r"^[0-9]{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/"
                r"[a-z0-9/_-]+@sha256:[0-9a-f]{64}$"
            )
        ),
    ]
    training_image_digest: Sha256
    training_image_source_tag: Annotated[str, Field(pattern=r"^sha-[0-9a-f]{40}$")]
    training_hardware: Literal["ml.m5.xlarge", "ml.g4dn.xlarge"]
    training_accelerator: Literal["cpu", "gpu"]
    training_region: Literal["us-east-1"]
    training_status: Literal["succeeded"]
    training_billable_on_demand_upper_bound_usd: NonNegativeDecimal
    training_run_manifest_s3_key: Annotated[
        str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+/reports/run-manifest\.json$")
    ]
    training_run_manifest_sha256: Sha256
    source_identity_basis: Literal["clean checkout and exact sha-commit ECR tag-to-digest binding"]

    @model_validator(mode="after")
    def identities_and_preregistered_role_match(self) -> CandidateReleaseInputs:
        run_marker = f"runs/{self.candidate_run_id}/"
        if not self.candidate_artifact_s3_key.startswith(f"runs/{self.candidate_run_id}/"):
            raise ValueError("candidate artifact key is outside the candidate run")
        if not self.candidate_training_config_s3_key.startswith(run_marker):
            raise ValueError("candidate config key is outside the candidate run")
        if not self.training_run_manifest_s3_key.startswith(run_marker):
            raise ValueError("run-manifest key is outside the candidate run")
        if not self.training_image_uri.endswith("@" + self.training_image_digest):
            raise ValueError("training image URI and digest differ")
        if self.training_image_source_tag != "sha-" + self.git_sha:
            raise ValueError("training image source tag and Git SHA differ")
        if self.training_hardware.endswith("g4dn.xlarge") != (self.training_accelerator == "gpu"):
            raise ValueError("training hardware and accelerator differ")
        expected = {
            "candidate_treatment": (
                "configs/experiments/candidate-v1.yaml",
                {"development", "final"},
            ),
            "random_negative_control": (
                "configs/experiments/candidate-random-ablation-v1.yaml",
                {"ablation"},
            ),
            "title_only_control": (
                "configs/experiments/candidate-title-ablation-v1.yaml",
                {"ablation"},
            ),
        }
        path, run_kinds = expected[self.training_config_role]
        if self.candidate_training_config_path != path or self.training_run_kind not in run_kinds:
            raise ValueError("training role, committed config, and run kind differ")
        return self


class ProtectedFinancialSnapshot(ContractModel):
    """Sanitized provenance for protected spend and applicable-credit inputs."""

    schema_version: Literal["1.0.0"]
    observed_at: UtcDateTime
    validated_at: UtcDateTime
    maximum_age_seconds: Literal[21_600]
    age_seconds_at_validation: Annotated[int, Field(ge=0, le=21_600)]
    source: Literal["aws_billing_and_cost_management_console"]
    authorization_workflow: Annotated[
        str,
        Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"),
    ]
    authorization_operation_id: Annotated[
        str,
        Field(min_length=71, max_length=71, pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    authorization_input_sha256: Annotated[
        str,
        Field(min_length=71, max_length=71, pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    authorization_commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    authorization_reservation_sha256: Annotated[
        str,
        Field(min_length=71, max_length=71, pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    receipt_binding_algorithm: Literal["hmac-sha256-v2"]
    receipt_sha256: Annotated[
        str,
        Field(
            min_length=71,
            max_length=71,
            pattern=r"^sha256:[0-9a-f]*[1-9a-f][0-9a-f]*$",
        ),
    ]
    campaign_spend_to_date_redacted: Literal[True]
    remaining_applicable_credit_redacted: Literal[True]

    @model_validator(mode="after")
    def observation_age_is_exact_and_bounded(self) -> ProtectedFinancialSnapshot:
        elapsed_seconds = (self.validated_at - self.observed_at).total_seconds()
        if elapsed_seconds < 0:
            raise ValueError("financial snapshot observation is in the future")
        expected_age = math.ceil(elapsed_seconds)
        if expected_age != self.age_seconds_at_validation:
            raise ValueError("financial snapshot age evidence is inconsistent")
        if expected_age > self.maximum_age_seconds:
            raise ValueError("financial snapshot is stale")
        return self


class TrainingCostPreflight(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["training_cost_preflight"]
    region: Literal["us-east-1"]
    instance_type: Literal["ml.m5.xlarge", "ml.g4dn.xlarge"]
    accelerator: Literal["cpu", "gpu"]
    maximum_runtime_seconds: Annotated[int, Field(ge=1, le=18_000)]
    on_demand_hourly_upper_bound_usd: NonNegativeDecimal
    maximum_job_estimate_usd: NonNegativeDecimal
    campaign_and_credit_guard_passed: Literal[True]
    credit_balance_redacted_from_public_evidence: Literal[True]
    required_credit_reserve_usd: NonNegativeDecimal
    maximum_out_of_pocket_usd: NonNegativeDecimal
    pricing_basis: Literal["live AWS Price List response; highest matching hourly dimension"]
    financial_snapshot: ProtectedFinancialSnapshot

    @model_validator(mode="after")
    def zero_cash_risk_and_hardware_match(self) -> TrainingCostPreflight:
        if self.maximum_out_of_pocket_usd != 0:
            raise ValueError("training cost preflight must enforce zero out-of-pocket")
        if self.required_credit_reserve_usd < 40:
            raise ValueError("training cost preflight must preserve the USD 40 reserve")
        if self.instance_type.endswith("g4dn.xlarge") != (self.accelerator == "gpu"):
            raise ValueError("training cost hardware and accelerator differ")
        return self


class SageMakerManagedSpotQuotaPreflight(ContractModel):
    """Sanitized live Service Quotas evidence captured before training submission."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["sagemaker_managed_spot_quota_preflight"]
    checked_at: UtcDateTime
    region: Literal["us-east-1"]
    service_code: Literal["sagemaker"]
    instance_type: Literal["ml.m5.xlarge", "ml.g4dn.xlarge"]
    quota_code: Literal["L-4CEE6BA6", "L-944F78BB"]
    quota_name: Literal[
        "ml.m5.xlarge for spot training job usage",
        "ml.g4dn.xlarge for spot training job usage",
    ]
    applied_value: PositiveFloat
    required_value: Literal[1]
    quota_guard_passed: Literal[True]

    @model_validator(mode="after")
    def exact_instance_quota_mapping_and_capacity(self) -> SageMakerManagedSpotQuotaPreflight:
        expected = {
            "ml.m5.xlarge": (
                "L-4CEE6BA6",
                "ml.m5.xlarge for spot training job usage",
            ),
            "ml.g4dn.xlarge": (
                "L-944F78BB",
                "ml.g4dn.xlarge for spot training job usage",
            ),
        }
        if (self.quota_code, self.quota_name) != expected[self.instance_type]:
            raise ValueError("managed-spot quota does not match the requested instance type")
        if self.applied_value < self.required_value:
            raise ValueError("managed-spot quota has no capacity for one training instance")
        return self


class SageMakerProcessingQuotaPreflight(ContractModel):
    """Sanitized live Service Quotas evidence captured before held-out processing."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["sagemaker_processing_quota_preflight"]
    checked_at: UtcDateTime
    region: Literal["us-east-1"]
    service_code: Literal["sagemaker"]
    instance_type: Literal["ml.m5.xlarge"]
    quota_code: Literal["L-0307F515"]
    quota_name: Literal["ml.m5.xlarge for processing job usage"]
    applied_value: PositiveFloat
    required_value: Literal[1]
    quota_guard_passed: Literal[True]

    @model_validator(mode="after")
    def exact_processing_quota_mapping_and_capacity(self) -> SageMakerProcessingQuotaPreflight:
        expected = (
            "ml.m5.xlarge",
            "L-0307F515",
            "ml.m5.xlarge for processing job usage",
        )
        observed = (self.instance_type, self.quota_code, self.quota_name)
        if observed != expected:
            raise ValueError("processing quota does not match the required instance type")
        if not math.isfinite(self.applied_value) or self.applied_value < self.required_value:
            raise ValueError("processing quota has no capacity for one processing instance")
        return self


class EvaluationCostPreflight(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["evaluation_cost_preflight"]
    guard_passed: Literal[True]
    region: Literal["us-east-1"]
    instance_type: Literal["ml.m5.xlarge"]
    independent_processing_job_count: Literal[2]
    maximum_runtime_seconds_per_job: Annotated[int, Field(ge=1, le=7200)]
    maximum_total_instance_hours: NonNegativeDecimal
    on_demand_hourly_upper_bound_usd: NonNegativeDecimal
    maximum_job_estimate_usd: NonNegativeDecimal
    required_credit_reserve_usd: NonNegativeDecimal
    maximum_out_of_pocket_usd: NonNegativeDecimal
    financial_snapshot: ProtectedFinancialSnapshot

    @model_validator(mode="after")
    def zero_cash_risk_and_runtime_match(self) -> EvaluationCostPreflight:
        if self.maximum_out_of_pocket_usd != 0:
            raise ValueError("evaluation cost preflight must enforce zero out-of-pocket")
        if self.required_credit_reserve_usd < 40:
            raise ValueError("evaluation cost preflight must preserve the USD 40 reserve")
        expected_hours = Decimal(self.maximum_runtime_seconds_per_job * 2) / Decimal(3600)
        if self.maximum_total_instance_hours < expected_hours:
            raise ValueError("evaluation cost preflight understates total instance hours")
        return self


class BenchmarkCostPreflight(ContractModel):
    schema_version: Literal["1.0.0"]
    artifact_type: Literal["benchmark_cost_preflight"]
    status: Literal["passed"]
    checked_at: UtcDateTime
    benchmark_run_id: Annotated[str, Field(pattern=r"^github-[0-9]+-attempt-[1-9][0-9]*$")]
    release_id: NonEmptyStr
    model_id: NonEmptyStr
    region: Literal["us-east-1"]
    public_origin: CloudFrontOrigin
    maximum_out_of_pocket_usd: NonNegativeDecimal
    campaign_envelope_usd: NonNegativeDecimal
    required_credit_reserve_usd: NonNegativeDecimal
    conservative_benchmark_allowance_usd: NonNegativeDecimal
    heldout_access_enabled: Literal[False]
    sensitive_balance_values_recorded: Literal[False]
    financial_snapshot: ProtectedFinancialSnapshot

    @model_validator(mode="after")
    def approved_boundaries_are_exact(self) -> BenchmarkCostPreflight:
        if self.maximum_out_of_pocket_usd != 0:
            raise ValueError("benchmark preflight must enforce zero out-of-pocket")
        if self.campaign_envelope_usd != 40 or self.required_credit_reserve_usd < 40:
            raise ValueError("benchmark preflight must preserve the approved USD 40 envelope")
        return self


class ThreePercentileLatency(ContractModel):
    p50: NonNegativeFloat
    p95: NonNegativeFloat
    p99: NonNegativeFloat

    @model_validator(mode="after")
    def percentiles_are_monotonic(self) -> ThreePercentileLatency:
        if not self.p50 <= self.p95 <= self.p99:
            raise ValueError("latency percentiles must satisfy p50 <= p95 <= p99")
        return self


class CandidateApiGate(ContractModel):
    schema_version: Literal["1.0.0"]
    status: Literal["passed"]
    scope: Literal["candidate_alias_primary_release_gate"]
    valid_request_count: Literal[200]
    failure_count: Annotated[int, Field(ge=0, le=1)]
    error_rate: Annotated[float, Field(ge=0, lt=0.01, allow_inf_nan=False)]
    error_rate_target: Literal["less_than_0.01"]
    warmup_request_count: Literal[10]
    candidate_count: Literal[40]
    concurrency: Literal[1]
    end_to_end_latency_ms: ThreePercentileLatency
    model_latency_ms: ThreePercentileLatency
    lambda_memory_mb: Literal[4096]
    architecture: Literal["x86_64"]
    region: Literal["us-east-1"]
    reserved_concurrency: Literal[2]
    provisioned_concurrency: Literal[0]
    measurement_phase: Literal["warm_after_ten_explicit_warmups"]
    controlled_cold_start_evidence_file: Literal["candidate-cold-start.json"]
    controlled_cold_sample_included: Literal[False]
    limitations: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def error_rate_matches_failures(self) -> CandidateApiGate:
        if not math.isclose(
            self.error_rate,
            self.failure_count / self.valid_request_count,
            rel_tol=0,
            abs_tol=1e-15,
        ):
            raise ValueError("candidate API error rate differs from request counts")
        return self


class SmokeLatency(ContractModel):
    minimum: NonNegativeFloat
    median: NonNegativeFloat
    maximum: NonNegativeFloat
    rank_median: NonNegativeFloat

    @model_validator(mode="after")
    def summary_is_ordered(self) -> SmokeLatency:
        if not self.minimum <= self.median <= self.maximum:
            raise ValueError("smoke latency must satisfy minimum <= median <= maximum")
        return self


class SmokeTestEvidence(ContractModel):
    schema_version: Literal["1.0.0"]
    status: Literal["passed"]
    scope: Literal["bounded_release_smoke"]
    base_url_origin: Annotated[str, Field(pattern=r"^https?://[^/?#]+$")]
    model_id: NonEmptyStr
    evaluated_candidate_model_id: NonEmptyStr
    query_id: NonEmptyStr
    candidate_count: Annotated[int, Field(ge=1, le=40)]
    rank_requests: Annotated[int, Field(ge=1, le=20)]
    comparison_checked: bool
    request_count: Annotated[int, Field(ge=5)]
    error_count: Literal[0]
    latency_ms: SmokeLatency
    production_error_rate_claim_eligible: Literal[False]
    note: NonEmptyStr


class BrowserSmoke(ContractModel):
    desktop: Literal[True]
    mobile: Literal[True]
    keyboard: Literal[True]


class DeploymentEvidence(ContractModel):
    """Successful production activation, including the separate cold observation."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["deployment_evidence"]
    release_id: NonEmptyStr
    model_id: NonEmptyStr
    code_commit: FullGitSha
    serving_image_digest: Sha256
    previous_lambda_version: LambdaVersion
    production_lambda_version: LambdaVersion
    promoted_pointer_version_id: NonEmptyStr
    smoke_tests_passed: Literal[True]
    controlled_cold_start: ColdStartEvidence
    candidate_api_gate: CandidateApiGate
    production_api_smoke: SmokeTestEvidence
    browser_smoke: BrowserSmoke

    @model_validator(mode="after")
    def deployment_identities_match(self) -> DeploymentEvidence:
        cold = self.controlled_cold_start.identifiers
        if cold.release_id != self.release_id or cold.model_id != self.model_id:
            raise ValueError("controlled cold-start identity differs from deployment")
        if cold.function_version != self.production_lambda_version:
            raise ValueError("cold-start version differs from activated production version")
        if self.production_api_smoke.model_id != self.model_id:
            raise ValueError("production smoke exercised a different active model")
        return self


class AutomaticDeploymentRollback(ContractModel):
    """Compensating rollback after a candidate crossed the activation boundary."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["automatic_deployment_rollback"]
    status: Literal["automatically_rolled_back"]
    rollback_trigger: Literal["production_verification_failed", "post_activation_failure"]
    failed_release_id: NonEmptyStr
    restored_lambda_version: LambdaVersion
    restored_pointer_version_id: NonEmptyStr
    service_disabled: bool


class ManualRollbackEvidence(ContractModel):
    """Successful operator-authorized restoration of a versioned public release."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["manual_rollback_evidence"]
    restored_release_id: NonEmptyStr
    restored_model_id: NonEmptyStr
    from_lambda_version: LambdaVersion
    to_lambda_version: LambdaVersion
    restored_pointer_version_id: NonEmptyStr
    workflow_commit: FullGitSha
    smoke_test_passed: Literal[True]


class BenchmarkLambdaConfiguration(ContractModel):
    schema_version: Literal["1.0.0"]
    checked_at: UtcDateTime
    benchmark_run_id: Annotated[str, Field(pattern=r"^github-[0-9]+-attempt-[1-9][0-9]*$")]
    release_id: NonEmptyStr
    model_id: NonEmptyStr
    function_name: NonEmptyStr
    alias: Literal["production"]
    function_version: LambdaVersion
    memory_mb: Literal[4096]
    architecture: Literal["x86_64"]
    reserved_concurrency: Literal[2]
    provisioned_concurrency: Literal[0]
    provisioned_concurrency_verification: Literal[
        "live GetProvisionedConcurrencyConfig returned a not-found response"
    ]
    region: Literal["us-east-1"]


class BenchmarkIdentifiers(ContractModel):
    benchmark_run_id: Annotated[str, Field(pattern=r"^github-[0-9]+-attempt-[1-9][0-9]*$")]
    release_id: NonEmptyStr
    public_run_id: NonEmptyStr
    model_id: NonEmptyStr
    evidence_mode: Literal["validation_only", "verified"]
    release_git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$")]
    benchmark_harness_git_sha: FullGitSha
    dataset_manifest_hash: Sha256
    model_artifact_checksum: Sha256
    region: Literal["us-east-1"]
    public_origin: CloudFrontOrigin


class BenchmarkReleaseBinding(ContractModel):
    promotion_pointer_version_id: NonEmptyStr
    promotion_pointer_etag: NonEmptyStr
    bundle_s3_key: NonEmptyStr
    release_manifest_sha256: Sha256
    public_evidence_sha256: Sha256
    bundle_checksums_sha256: Sha256
    deployment_evidence_version_id: NonEmptyStr
    deployment_evidence_etag: NonEmptyStr
    deployment_evidence_sha256: Sha256


class BenchmarkProtocol(ContractModel):
    measurement_class: Literal["warm_after_explicit_per_condition_warmups"]
    candidate_counts: tuple[Literal[10], Literal[20], Literal[40]]
    offered_concurrency_levels: tuple[Literal[1], Literal[4], Literal[8]]
    warmup_requests_per_condition: Literal[10]
    measured_requests_per_condition: Literal[200]
    condition_count: Literal[9]
    request_timeout_seconds: Annotated[int, Field(ge=1, le=30)]
    response_size_limit_bytes: Literal[1_048_576]
    minimum_warmup_successes_per_condition: Literal[1]
    primary_latency_candidate_count: Literal[40]
    primary_latency_offered_concurrency: Literal[1]
    primary_latency_minimum_successes: Literal[199]
    secondary_latency_minimum_successes: Literal[20]
    controlled_cold_sample_included: Literal[False]
    pre_benchmark_observations_included: Literal[False]


class EndpointObservation(ContractModel):
    http_status: Literal[200]
    end_to_end_ms: NonNegativeFloat


class HealthObservation(EndpointObservation):
    service_status: Literal["ok"]


class BenchmarkSample(ContractModel):
    ordinal: Annotated[int, Field(ge=1, le=200)]
    ok: bool
    http_status: Annotated[int, Field(ge=100, le=599)] | None
    throttled: bool
    end_to_end_ms: NonNegativeFloat
    model_ms: NonNegativeFloat | None = None
    error_category: (
        Literal["http_throttle", "http_error", "invalid_response", "transport_error"] | None
    ) = None

    @model_validator(mode="after")
    def success_and_failure_fields_are_disjoint(self) -> BenchmarkSample:
        if self.ok:
            if self.http_status != 200 or self.throttled or self.model_ms is None:
                raise ValueError("successful benchmark sample has inconsistent fields")
            if self.error_category is not None:
                raise ValueError("successful benchmark sample cannot name an error")
        else:
            if self.model_ms is not None or self.error_category is None:
                raise ValueError("failed benchmark sample must name only its error category")
            if self.throttled != (self.error_category == "http_throttle"):
                raise ValueError("benchmark throttle flag and category differ")
        return self


class BenchmarkLatencySummary(ContractModel):
    p50: NonNegativeFloat
    p95: NonNegativeFloat
    p99: NonNegativeFloat
    mean: NonNegativeFloat
    minimum: NonNegativeFloat
    maximum: NonNegativeFloat

    @model_validator(mode="after")
    def summary_is_ordered(self) -> BenchmarkLatencySummary:
        if not self.minimum <= self.p50 <= self.p95 <= self.p99 <= self.maximum:
            raise ValueError("benchmark latency summary is not monotonic")
        if not self.minimum <= self.mean <= self.maximum:
            raise ValueError("benchmark latency mean is outside the observed range")
        return self


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


class BenchmarkSampleSummary(ContractModel):
    sample_count: Annotated[int, Field(ge=1, le=200)]
    success_count: Annotated[int, Field(ge=0, le=200)]
    error_count: Annotated[int, Field(ge=0, le=200)]
    throttle_count: Annotated[int, Field(ge=0, le=200)]
    http_status_and_transport_counts: dict[NonEmptyStr, Annotated[int, Field(ge=1)]]
    end_to_end_latency_ms: BenchmarkLatencySummary | None
    model_latency_ms: BenchmarkLatencySummary | None
    samples: Annotated[list[BenchmarkSample], Field(min_length=1, max_length=200)]

    @staticmethod
    def _validate_summary(
        summary: BenchmarkLatencySummary | None, values: list[float], label: str
    ) -> None:
        if not values:
            if summary is not None:
                raise ValueError(f"{label} must be null without successful samples")
            return
        if summary is None:
            raise ValueError(f"{label} is required for successful samples")
        expected = {
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "mean": statistics.fmean(values),
            "minimum": min(values),
            "maximum": max(values),
        }
        for name, value in expected.items():
            if not math.isclose(getattr(summary, name), value, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(f"{label}.{name} differs from raw samples")

    @model_validator(mode="after")
    def aggregates_match_raw_samples(self) -> BenchmarkSampleSummary:
        if len(self.samples) != self.sample_count:
            raise ValueError("benchmark sample_count differs from raw samples")
        if [sample.ordinal for sample in self.samples] != list(range(1, self.sample_count + 1)):
            raise ValueError("benchmark sample ordinals must be complete and ordered")
        successful = [sample for sample in self.samples if sample.ok]
        if self.success_count != len(successful) or self.error_count != self.sample_count - len(
            successful
        ):
            raise ValueError("benchmark success/error totals differ from raw samples")
        if self.throttle_count != sum(sample.throttled for sample in self.samples):
            raise ValueError("benchmark throttle total differs from raw samples")
        observed: dict[str, int] = {}
        for sample in self.samples:
            key = (
                str(sample.http_status)
                if sample.http_status is not None
                else str(sample.error_category)
            )
            observed[key] = observed.get(key, 0) + 1
        if self.http_status_and_transport_counts != dict(sorted(observed.items())):
            raise ValueError("benchmark status counts differ from raw samples")
        self._validate_summary(
            self.end_to_end_latency_ms,
            [sample.end_to_end_ms for sample in successful],
            "end_to_end_latency_ms",
        )
        self._validate_summary(
            self.model_latency_ms,
            [sample.model_ms for sample in successful if sample.model_ms is not None],
            "model_latency_ms",
        )
        return self


class BenchmarkCondition(ContractModel):
    candidate_count: Literal[10, 20, 40]
    query_id: NonEmptyStr
    offered_concurrency: Literal[1, 4, 8]
    warmup: BenchmarkSampleSummary
    measured: BenchmarkSampleSummary

    @model_validator(mode="after")
    def phase_counts_are_exact(self) -> BenchmarkCondition:
        if self.warmup.sample_count != 10 or self.measured.sample_count != 200:
            raise ValueError("each benchmark condition requires 10 warmups and 200 measurements")
        return self


class PreBenchmarkObservations(ContractModel):
    cold_start_controlled: Literal[False]
    health: HealthObservation
    ready: EndpointObservation
    models: EndpointObservation
    queries: EndpointObservation
    run_evidence: EndpointObservation
    first_rank: BenchmarkSample
    excluded_from_warm_latency_percentiles: Literal[True]

    @model_validator(mode="after")
    def first_rank_is_a_successful_separate_observation(self) -> PreBenchmarkObservations:
        if not self.first_rank.ok:
            raise ValueError("pre-benchmark first-rank observation must succeed")
        return self


class BenchmarkTotals(ContractModel):
    warmup_request_count: Literal[90]
    measured_request_count: Literal[1800]
    measured_success_count: Annotated[int, Field(ge=0, le=1800)]
    measured_error_count: Annotated[int, Field(ge=0, le=1800)]
    measured_throttle_count: Annotated[int, Field(ge=0, le=1800)]


class BenchmarkInterpretation(ContractModel):
    latency_claim: Literal[
        "Warm public CloudFront end-to-end and model latency over successful responses after "
        "explicit warmups. The primary 40-candidate, concurrency-one condition has at least "
        "199 successes from 200 attempts (error rate below one percent); every secondary "
        "condition has at least 20 successes. The controlled candidate cold start is reported "
        "separately."
    ]
    throughput_claim_eligible: Literal[False]
    scaling_claim_eligible: Literal[False]
    concurrency_above_reserved_expected_to_expose_bound: tuple[Literal[4], Literal[8]]
    reserved_concurrency_is_a_cost_and_capacity_bound: Literal[True]


class PerformanceReport(ContractModel):
    """Complete fixed-matrix public serving benchmark with raw observations."""

    schema_version: Literal["1.0.0"]
    artifact_type: Literal["serving_performance_report"]
    status: Literal["completed"]
    scope: Literal["manual_post_deployment_lambda_performance_protocol"]
    started_at: UtcDateTime
    completed_at: UtcDateTime
    identifiers: BenchmarkIdentifiers
    release_binding: BenchmarkReleaseBinding
    lambda_configuration: BenchmarkLambdaConfiguration
    controlled_cold_start: ColdStartEvidence
    protocol: BenchmarkProtocol
    pre_benchmark_observations: PreBenchmarkObservations
    conditions: Annotated[list[BenchmarkCondition], Field(min_length=9, max_length=9)]
    totals: BenchmarkTotals
    interpretation: BenchmarkInterpretation
    limitations: Annotated[list[NonEmptyStr], Field(min_length=5)]

    @model_validator(mode="after")
    def fixed_matrix_and_release_bindings_are_exact(self) -> PerformanceReport:
        if self.completed_at < self.started_at:
            raise ValueError("performance completion precedes start")
        expected_matrix = {
            (count, concurrency) for count in (10, 20, 40) for concurrency in (1, 4, 8)
        }
        observed_matrix = {
            (condition.candidate_count, condition.offered_concurrency)
            for condition in self.conditions
        }
        if observed_matrix != expected_matrix:
            raise ValueError("performance condition matrix is incomplete or duplicated")
        for condition in self.conditions:
            if (
                condition.warmup.success_count
                < self.protocol.minimum_warmup_successes_per_condition
            ):
                raise ValueError("every benchmark condition requires a successful warmup")
            primary = (
                condition.candidate_count == self.protocol.primary_latency_candidate_count
                and condition.offered_concurrency
                == self.protocol.primary_latency_offered_concurrency
            )
            minimum = (
                self.protocol.primary_latency_minimum_successes
                if primary
                else self.protocol.secondary_latency_minimum_successes
            )
            if condition.measured.success_count < minimum:
                label = "primary" if primary else "secondary"
                raise ValueError(f"{label} benchmark condition has too few successful measurements")
        warmups = [sample for condition in self.conditions for sample in condition.warmup.samples]
        measured = [
            sample for condition in self.conditions for sample in condition.measured.samples
        ]
        if (
            len(warmups) != self.totals.warmup_request_count
            or len(measured) != self.totals.measured_request_count
        ):
            raise ValueError("performance totals differ from the fixed matrix")
        if self.totals.measured_success_count != sum(sample.ok for sample in measured):
            raise ValueError("performance success total differs from raw samples")
        if self.totals.measured_error_count != sum(not sample.ok for sample in measured):
            raise ValueError("performance error total differs from raw samples")
        if self.totals.measured_throttle_count != sum(sample.throttled for sample in measured):
            raise ValueError("performance throttle total differs from raw samples")
        cold_ids = self.controlled_cold_start.identifiers
        if (
            self.lambda_configuration.benchmark_run_id != self.identifiers.benchmark_run_id
            or self.lambda_configuration.release_id != self.identifiers.release_id
            or self.lambda_configuration.model_id != self.identifiers.model_id
            or cold_ids.release_id != self.identifiers.release_id
            or cold_ids.model_id != self.identifiers.model_id
            or cold_ids.dataset_manifest_hash != self.identifiers.dataset_manifest_hash
            or cold_ids.model_artifact_checksum != self.identifiers.model_artifact_checksum
            or cold_ids.function_name != self.lambda_configuration.function_name
            or cold_ids.function_version != self.lambda_configuration.function_version
        ):
            raise ValueError("performance report identities differ from cold/Lambda evidence")
        return self


class PerformanceValidation(ContractModel):
    schema_version: Literal["1.0.0"]
    status: Literal["passed"]
    validated_at: UtcDateTime
    benchmark_run_id: Annotated[str, Field(pattern=r"^github-[0-9]+-attempt-[1-9][0-9]*$")]
    release_id: NonEmptyStr
    model_id: NonEmptyStr
    performance_report_sha256: Sha256
    evidence_file_count: Literal[5]
    condition_count: Literal[9]
    controlled_cold_start_sample_count: Literal[1]
    warmup_request_count: Literal[90]
    measured_request_count: Literal[1800]
    success_thresholds_enforced: Literal[True]
    minimum_warmup_condition_success_count: Annotated[int, Field(ge=1, le=10)]
    primary_latency_condition_success_count: Annotated[int, Field(ge=199, le=200)]
    minimum_secondary_condition_success_count: Annotated[int, Field(ge=20, le=200)]
    immutability_required: Literal[True]


__all__ = [
    "AutomaticDeploymentRollback",
    "BenchmarkCostPreflight",
    "BenchmarkLambdaConfiguration",
    "CandidateApiGate",
    "CandidateReleaseInputs",
    "CloudTrainingJobEvidence",
    "DeploymentEvidence",
    "EvaluationCostPreflight",
    "ManualRollbackEvidence",
    "PerformanceReport",
    "PerformanceValidation",
    "ProtectedFinancialSnapshot",
    "SageMakerManagedSpotQuotaPreflight",
    "SageMakerProcessingQuotaPreflight",
    "SmokeTestEvidence",
    "TrainingCostPreflight",
    "TrainingImageProvenance",
]
