"""Immutable validation-only trial-selection evidence contract."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, SchemaVersion, Sha256

TrialRole = Literal[
    "candidate_treatment",
    "random_negative_control",
    "title_only_control",
]


class ValidationTrial(ContractModel):
    """One checksummed cloud-training result used by the frozen comparison."""

    role: TrialRole
    promotion_eligible: bool
    candidate_run_id: NonEmptyStr
    candidate_model_id: NonEmptyStr
    candidate_artifact_s3_key: Annotated[str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+\.tar\.gz$")]
    candidate_artifact_sha256: Sha256
    candidate_checkpoint_sha256: Sha256
    candidate_release_inputs_s3_key: Annotated[
        str,
        Field(pattern=r"^runs/[A-Za-z0-9._/-]+/reports/candidate-release-inputs\.json$"),
    ]
    candidate_release_inputs_sha256: Sha256
    training_run_manifest_s3_key: Annotated[
        str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+/reports/run-manifest\.json$")
    ]
    training_run_manifest_sha256: Sha256
    training_summary_sha256: Sha256
    frozen_config_file_sha256: Sha256
    candidate_training_config_path: Annotated[
        str, Field(pattern=r"^configs/experiments/[A-Za-z0-9._/-]+\.ya?ml$")
    ]
    candidate_training_config_s3_key: Annotated[
        str, Field(pattern=r"^runs/[A-Za-z0-9._/-]+/config/experiment\.yaml$")
    ]
    candidate_training_config_file_sha256: Sha256
    candidate_training_config_sha256: Sha256
    config_id: NonEmptyStr
    dataset_manifest_hash: Sha256
    input_template_version: Literal["title_v1", "enriched_v1"]
    sampling_strategy: Literal["mixed_hard_random_v1", "random_only_v1"]
    hard_example_sources: list[Literal["bm25", "pretrained_cross_encoder"]]
    best_validation_ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    training_git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    repository_dirty: Literal[False]
    training_run_kind: Literal["ablation", "final"]
    training_config_role: TrialRole
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
    training_job_id: NonEmptyStr
    region: Literal["us-east-1"]
    hardware_class: Literal["ml.m5.xlarge", "ml.g4dn.xlarge"]
    accelerator: Literal["cpu", "gpu"]
    training_billable_on_demand_upper_bound_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    source_identity_basis: Literal["clean checkout and exact sha-commit ECR tag-to-digest binding"]

    @model_validator(mode="after")
    def role_has_exact_treatment(self) -> ValidationTrial:
        expected = {
            "candidate_treatment": (
                True,
                "candidate-v1",
                "configs/experiments/candidate-v1.yaml",
                "enriched_v1",
                "mixed_hard_random_v1",
                {"bm25", "pretrained_cross_encoder"},
                "final",
                "candidate_treatment",
            ),
            "random_negative_control": (
                False,
                "candidate-random-ablation-v1",
                "configs/experiments/candidate-random-ablation-v1.yaml",
                "enriched_v1",
                "random_only_v1",
                set(),
                "ablation",
                "random_negative_control",
            ),
            "title_only_control": (
                False,
                "candidate-title-ablation-v1",
                "configs/experiments/candidate-title-ablation-v1.yaml",
                "title_v1",
                "mixed_hard_random_v1",
                {"bm25", "pretrained_cross_encoder"},
                "ablation",
                "title_only_control",
            ),
        }
        eligible, config_id, config_path, template, strategy, sources, run_kind, config_role = (
            expected[self.role]
        )
        observed = (
            self.promotion_eligible,
            self.config_id,
            self.candidate_training_config_path,
            self.input_template_version,
            self.sampling_strategy,
            set(self.hard_example_sources),
            self.training_run_kind,
            self.training_config_role,
        )
        if observed != (
            eligible,
            config_id,
            config_path,
            template,
            strategy,
            sources,
            run_kind,
            config_role,
        ):
            raise ValueError(f"{self.role} does not match its preregistered treatment contract")
        if len(self.hard_example_sources) != len(set(self.hard_example_sources)):
            raise ValueError("hard-example sources must be unique")
        if self.hardware_class.endswith("g4dn.xlarge") != (self.accelerator == "gpu"):
            raise ValueError("training hardware and accelerator do not match")
        if not self.training_image_uri.endswith("@" + self.training_image_digest):
            raise ValueError("training image URI and digest do not match")
        if self.training_image_source_tag != "sha-" + self.training_git_sha:
            raise ValueError("training image source tag and Git SHA do not match")
        return self


class ValidationContrast(ContractModel):
    """One predeclared single-factor validation comparison."""

    contrast_id: Literal["mixed_vs_random_sampling", "enriched_vs_title_input"]
    treatment_role: Literal["candidate_treatment"]
    control_role: Literal["random_negative_control", "title_only_control"]
    controlled_difference_fields: list[NonEmptyStr]
    treatment_validation_ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    control_validation_ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    treatment_minus_control: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]


class TrialSelection(ContractModel):
    """Frozen, validation-only evidence required before held-out access."""

    schema_version: SchemaVersion
    artifact_type: Literal["validation_trial_selection"]
    selection_id: Annotated[str, Field(pattern=r"^trial-selection-[0-9a-f]{20}$")]
    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    repository_dirty: Literal[False]
    dataset_manifest_hash: Sha256
    split: Literal["validation"]
    metric_name: Literal["graded_ndcg@10"]
    test_access_count: Literal[0]
    heldout_accessed: Literal[False]
    trial_count: Literal[3]
    selection_rule_id: Literal["preregistered_treatment_controls_validation_only_v1"]
    selection_rule: NonEmptyStr
    selected_role: Literal["candidate_treatment"]
    selected_candidate_run_id: NonEmptyStr
    selected_candidate_model_id: NonEmptyStr
    selected_candidate_config_sha256: Sha256
    trials: list[ValidationTrial]
    contrasts: list[ValidationContrast]

    @model_validator(mode="after")
    def comparison_is_complete_and_frozen(self) -> TrialSelection:
        if len(self.trials) != self.trial_count:
            raise ValueError("trial_count must equal the exact trial inventory")
        by_role: dict[str, ValidationTrial] = {trial.role: trial for trial in self.trials}
        required_roles = {
            "candidate_treatment",
            "random_negative_control",
            "title_only_control",
        }
        if set(by_role) != required_roles or len(by_role) != len(self.trials):
            raise ValueError("trial inventory must contain each mandatory role exactly once")

        treatment = by_role["candidate_treatment"]
        if (
            self.selected_candidate_run_id,
            self.selected_candidate_model_id,
            self.selected_candidate_config_sha256,
        ) != (
            treatment.candidate_run_id,
            treatment.candidate_model_id,
            treatment.candidate_training_config_sha256,
        ):
            raise ValueError("selected candidate must be the preregistered treatment")

        shared_values = {
            (
                trial.dataset_manifest_hash,
                trial.training_git_sha,
                trial.training_image_digest,
                trial.region,
                trial.hardware_class,
                trial.accelerator,
            )
            for trial in self.trials
        }
        if len(shared_values) != 1 or self.dataset_manifest_hash != treatment.dataset_manifest_hash:
            raise ValueError("all trials must share data, code, image, region, and hardware")

        by_contrast: dict[str, ValidationContrast] = {
            contrast.contrast_id: contrast for contrast in self.contrasts
        }
        expected_contrasts = {
            "mixed_vs_random_sampling": (
                "random_negative_control",
                ["config_hash", "config_id", "hard_example_sources", "sampling_strategy"],
            ),
            "enriched_vs_title_input": (
                "title_only_control",
                ["config_hash", "config_id", "input_template_version"],
            ),
        }
        if set(by_contrast) != set(expected_contrasts) or len(by_contrast) != len(self.contrasts):
            raise ValueError("both mandatory contrasts must appear exactly once")
        for contrast_id, (control_role, fields) in expected_contrasts.items():
            contrast = by_contrast[contrast_id]
            control = by_role[control_role]
            if (
                contrast.control_role != control_role
                or contrast.controlled_difference_fields != fields
            ):
                raise ValueError(f"{contrast_id} does not disclose the exact controlled fields")
            expected_delta = (
                treatment.best_validation_ndcg_at_10 - control.best_validation_ndcg_at_10
            )
            if not (
                math.isclose(
                    contrast.treatment_validation_ndcg_at_10,
                    treatment.best_validation_ndcg_at_10,
                    rel_tol=0,
                    abs_tol=1e-15,
                )
                and math.isclose(
                    contrast.control_validation_ndcg_at_10,
                    control.best_validation_ndcg_at_10,
                    rel_tol=0,
                    abs_tol=1e-15,
                )
                and math.isclose(
                    contrast.treatment_minus_control,
                    expected_delta,
                    rel_tol=0,
                    abs_tol=1e-15,
                )
            ):
                raise ValueError(f"{contrast_id} values do not match the bound trials")
        return self


__all__ = [
    "TrialRole",
    "TrialSelection",
    "ValidationContrast",
    "ValidationTrial",
]
