"""Fail-closed Pydantic validation for training dispatch and durable evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from search_rank.schemas.experiment import ExperimentConfig
from search_rank.schemas.model import ModelArtifact
from search_rank.schemas.run import RunManifest
from search_rank.schemas.workflow import (
    CandidateReleaseInputs,
    CloudTrainingJobEvidence,
    SageMakerManagedSpotQuotaPreflight,
    TrainingCostPreflight,
    TrainingImageProvenance,
)

HARDWARE_ACCELERATOR = {
    "ml.m5.xlarge": "cpu",
    "ml.g4dn.xlarge": "gpu",
}
ModelT = TypeVar("ModelT", bound=BaseModel)


def _json_model(path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def validate_config(path: Path, *, instance_type: str, accelerator: str) -> ExperimentConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    experiment = ExperimentConfig.model_validate(payload)
    expected_accelerator = HARDWARE_ACCELERATOR.get(instance_type)
    if expected_accelerator is None:
        raise ValueError("training instance is outside the frozen hardware allowlist")
    if experiment.requested_hardware != instance_type:
        raise ValueError("frozen requested_hardware differs from the workflow instance")
    if accelerator != expected_accelerator:
        raise ValueError("workflow accelerator differs from the selected instance")
    return experiment


def validate_evidence(args: argparse.Namespace) -> None:
    experiment = validate_config(
        args.config,
        instance_type=args.instance_type,
        accelerator=args.accelerator,
    )
    model = _json_model(args.model_manifest, ModelArtifact)
    run = _json_model(args.run_manifest, RunManifest)
    candidate = _json_model(args.candidate_release_inputs, CandidateReleaseInputs)
    cost = _json_model(args.cost_preflight, TrainingCostPreflight)
    quota = _json_model(
        args.managed_spot_quota_preflight,
        SageMakerManagedSpotQuotaPreflight,
    )
    image = _json_model(args.training_image_provenance, TrainingImageProvenance)
    job = _json_model(args.cloud_training_job_evidence, CloudTrainingJobEvidence)
    actual = model.training_result
    if not (
        model.config_hash == experiment.config_hash
        and model.dataset_manifest_hash == experiment.dataset_manifest_hash
        and run.config_hash == experiment.config_hash
        and run.dataset_manifest_hash == experiment.dataset_manifest_hash
        and run.hardware == job.instance_type == candidate.training_hardware
        and run.accelerator
        == actual.accelerator_type
        == candidate.training_accelerator
        == job.accelerator
        and run.device_type == actual.device_type
        and run.cuda_available == actual.cuda_available
        and run.cuda_device_count == actual.cuda_device_count
        and candidate.candidate_model_id == model.model_id
        and candidate.candidate_run_id == run.run_id == job.training_job_name
        and candidate.git_sha == run.git_sha == job.git_sha == image.git_sha
        and candidate.training_image_digest == run.image_digest == image.image_digest
        and cost.instance_type == quota.instance_type == job.instance_type
    ):
        raise ValueError("durable training evidence identities are inconsistent")
    if args.accelerator == "gpu" and not (
        actual.device_type == "cuda"
        and actual.accelerator_type == "gpu"
        and actual.cuda_available
        and actual.cuda_device_count >= 1
    ):
        raise ValueError("GPU training evidence does not prove actual CUDA execution")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    config = subparsers.add_parser("config")
    config.add_argument("--config", type=Path, required=True)
    config.add_argument("--instance-type", required=True)
    config.add_argument("--accelerator", required=True)

    evidence = subparsers.add_parser("evidence")
    evidence.add_argument("--config", type=Path, required=True)
    evidence.add_argument("--instance-type", required=True)
    evidence.add_argument("--accelerator", required=True)
    for name in (
        "model-manifest",
        "run-manifest",
        "candidate-release-inputs",
        "cost-preflight",
        "managed-spot-quota-preflight",
        "training-image-provenance",
        "cloud-training-job-evidence",
    ):
        evidence.add_argument(f"--{name}", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "config":
        validate_config(
            args.config,
            instance_type=args.instance_type,
            accelerator=args.accelerator,
        )
    else:
        validate_evidence(args)


if __name__ == "__main__":
    main()
