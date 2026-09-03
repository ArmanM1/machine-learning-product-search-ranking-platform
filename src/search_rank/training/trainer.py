"""Deterministic pointwise cross-encoder fine-tuning entry point."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd
import torch
from sentence_transformers import CrossEncoder

from search_rank.baselines.cross_encoder import choose_device
from search_rank.evaluation.metrics import aggregate_query_metrics, rank_by_score
from search_rank.logging import log_event
from search_rank.schemas.experiment import ExperimentConfig

from .callbacks import CurvePoint, EarlyStopper, write_curves
from .checkpoints import assert_any_parameter_changed, load_checkpoint, snapshot_parameters

LOGGER = logging.getLogger(__name__)
_EPOCH_CHECKPOINT = re.compile(r"^epoch-([0-9]{4})$")


class _CrossEncoderPredictor(Protocol):
    def predict(self, sentences: list[tuple[str, str]], **kwargs: Any) -> Any: ...


def _predict_array(
    model: CrossEncoder,
    pairs: list[tuple[str, str]],
    **kwargs: Any,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    prediction = cast(_CrossEncoderPredictor, model).predict(pairs, **kwargs)
    return np.asarray(prediction, dtype=np.float64).reshape(-1)


@dataclass(frozen=True)
class TrainingResult:
    best_checkpoint: str
    best_validation_ndcg_at_10: float
    epochs_completed: int
    optimizer_steps: int
    duration_seconds: float
    changed_parameter_count: int
    curves_path: str
    fresh_load_verified: bool
    warmup_steps: int
    planned_optimizer_steps: int
    device_type: str
    cuda_available: bool
    cuda_device_count: int
    accelerator_type: str


@dataclass(frozen=True)
class _ResumeCheckpoint:
    directory: Path
    completed_epoch: int
    optimizer_steps: int
    best_epoch: int
    best_validation_ndcg_at_10: float
    patience_reference: float
    bad_epochs: int
    elapsed_training_seconds: float
    training_complete: bool
    curves: list[CurvePoint]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_inventory(directory: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in sorted(candidate for candidate in directory.rglob("*") if candidate.is_file()):
        relative = path.relative_to(directory).as_posix()
        if relative in {"COMPLETE", "checkpoint-manifest.json"}:
            continue
        if path.is_symlink():
            raise RuntimeError("managed-spot checkpoint contains a symbolic link")
        inventory[relative] = _file_sha256(path)
    return inventory


def _verify_checkpoint_commit(
    directory: Path,
    config: ExperimentConfig,
    expected_epoch: int,
) -> dict[str, Any]:
    complete_path = directory / "COMPLETE"
    manifest_path = directory / "checkpoint-manifest.json"
    if not complete_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("checkpoint commit marker or manifest is missing")
    manifest_bytes = manifest_path.read_bytes()
    expected_manifest_hash = complete_path.read_text(encoding="utf-8").strip()
    if expected_manifest_hash != "sha256:" + hashlib.sha256(manifest_bytes).hexdigest():
        raise RuntimeError("checkpoint commit marker does not match its manifest")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise RuntimeError("checkpoint manifest is not valid JSON") from error
    if set(manifest) != {
        "schema_version",
        "config_hash",
        "dataset_manifest_hash",
        "completed_epoch",
        "files",
    }:
        raise RuntimeError("checkpoint manifest fields are not exact")
    if not (
        manifest["schema_version"] == "1.0.0"
        and manifest["config_hash"] == config.config_hash
        and manifest["dataset_manifest_hash"] == config.dataset_manifest_hash
        and manifest["completed_epoch"] == expected_epoch
    ):
        raise RuntimeError("checkpoint manifest identity differs from the frozen experiment")
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise RuntimeError("checkpoint manifest has no file inventory")
    if any(
        not isinstance(name, str)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for name, digest in files.items()
    ):
        raise RuntimeError("checkpoint manifest contains an invalid file identity")
    if files != _checkpoint_inventory(directory):
        raise RuntimeError("checkpoint file inventory or checksum differs from its manifest")
    required = {"trainer-state.json", "optimizer-state.pt"}
    if not required.issubset(files) or not any(name.startswith("model/") for name in files):
        raise RuntimeError("checkpoint manifest omits required trainer state")
    return cast(dict[str, Any], manifest)


def _decode_checkpoint_metadata(
    directory: Path,
    checkpoint_root: Path,
    config: ExperimentConfig,
    expected_epoch: int,
) -> _ResumeCheckpoint:
    _verify_checkpoint_commit(directory, config, expected_epoch)
    metadata_path = directory / "trainer-state.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("checkpoint trainer metadata is invalid") from error
    if payload.get("schema_version") != "1.0.0":
        raise RuntimeError("managed-spot checkpoint has an unsupported schema version")
    if payload.get("config_hash") != config.config_hash:
        raise RuntimeError("managed-spot checkpoint configuration identity differs")
    if payload.get("dataset_manifest_hash") != config.dataset_manifest_hash:
        raise RuntimeError("managed-spot checkpoint dataset identity differs")
    try:
        completed_epoch = int(payload["completed_epoch"])
        optimizer_steps = int(payload["optimizer_steps"])
        best_epoch = int(payload["best_epoch"])
        best_metric = float(payload["best_validation_ndcg_at_10"])
        patience_reference = float(payload["patience_reference"])
        bad_epochs = int(payload["bad_epochs"])
        elapsed_seconds = float(payload["elapsed_training_seconds"])
        training_complete = payload["training_complete"]
        curves = [CurvePoint(**point) for point in payload["curves"]]
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("managed-spot checkpoint state is malformed") from error
    if completed_epoch != expected_epoch:
        raise RuntimeError("checkpoint directory and trainer epoch identities differ")
    if not isinstance(training_complete, bool):
        raise RuntimeError("managed-spot checkpoint completion flag is malformed")
    if not 1 <= completed_epoch <= config.max_epochs:
        raise RuntimeError("managed-spot checkpoint epoch is outside the frozen plan")
    if not 1 <= best_epoch <= completed_epoch:
        raise RuntimeError("managed-spot checkpoint best epoch is invalid")
    if optimizer_steps < 1 or bad_epochs < 0:
        raise RuntimeError("managed-spot checkpoint counters are invalid")
    if not all(
        math.isfinite(value) for value in (best_metric, patience_reference, elapsed_seconds)
    ):
        raise RuntimeError("managed-spot checkpoint contains a non-finite measurement")
    if elapsed_seconds < 0:
        raise RuntimeError("managed-spot checkpoint elapsed time is negative")
    if len(curves) != completed_epoch or [point.epoch for point in curves] != list(
        range(1, completed_epoch + 1)
    ):
        raise RuntimeError("managed-spot checkpoint curve history is incomplete")
    best_directory = checkpoint_root / f"epoch-{best_epoch:04d}"
    _verify_checkpoint_commit(best_directory, config, best_epoch)
    return _ResumeCheckpoint(
        directory=directory,
        completed_epoch=completed_epoch,
        optimizer_steps=optimizer_steps,
        best_epoch=best_epoch,
        best_validation_ndcg_at_10=best_metric,
        patience_reference=patience_reference,
        bad_epochs=bad_epochs,
        elapsed_training_seconds=elapsed_seconds,
        training_complete=training_complete,
        curves=curves,
    )


def _load_resume_checkpoint(
    checkpoint_root: Path,
    config: ExperimentConfig,
) -> _ResumeCheckpoint | None:
    """Use the newest valid commit, tolerating partially synchronized newer epochs."""

    if not checkpoint_root.exists():
        return None
    completed: list[tuple[int, Path]] = []
    for candidate in checkpoint_root.iterdir():
        match = _EPOCH_CHECKPOINT.fullmatch(candidate.name)
        if match and candidate.is_dir() and (candidate / "COMPLETE").is_file():
            completed.append((int(match.group(1)), candidate))
    if not completed:
        return None
    failures: list[str] = []
    for epoch, directory in sorted(completed, reverse=True):
        try:
            return _decode_checkpoint_metadata(directory, checkpoint_root, config, epoch)
        except (OSError, RuntimeError) as error:
            failures.append(f"{directory.name}: {error}")
            log_event(
                LOGGER,
                "training_checkpoint_rejected",
                checkpoint=directory.name,
                reason=str(error),
            )
    raise RuntimeError("no fully valid managed-spot checkpoint remains: " + "; ".join(failures))


def _capture_rng_state() -> dict[str, Any]:
    numpy_state = cast(tuple[Any, ...], np.random.get_state())
    return {
        "python": [
            int(numpy_value) if isinstance(numpy_value, np.integer) else numpy_value
            for numpy_value in random.getstate()
        ],
        "numpy": {
            "bit_generator": numpy_state[0],
            "state": numpy_state[1].astype(np.uint32).tolist(),
            "position": int(numpy_state[2]),
            "has_gauss": int(numpy_state[3]),
            "cached_gaussian": float(numpy_state[4]),
        },
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }


def _nested_tuple(value: Any) -> Any:
    return tuple(_nested_tuple(item) for item in value) if isinstance(value, list) else value


def _restore_rng_state(state: Any) -> None:
    if not isinstance(state, dict) or set(state) != {
        "python",
        "numpy",
        "torch_cpu",
        "torch_cuda",
    }:
        raise RuntimeError("managed-spot checkpoint RNG state is malformed")
    python_state = _nested_tuple(state["python"])
    numpy_state = state["numpy"]
    torch_cpu = state["torch_cpu"]
    torch_cuda = state["torch_cuda"]
    if not isinstance(numpy_state, dict) or set(numpy_state) != {
        "bit_generator",
        "state",
        "position",
        "has_gauss",
        "cached_gaussian",
    }:
        raise RuntimeError("managed-spot checkpoint NumPy RNG state is malformed")
    if not isinstance(torch_cpu, torch.Tensor) or not isinstance(torch_cuda, list):
        raise RuntimeError("managed-spot checkpoint Torch RNG state is malformed")
    try:
        random.setstate(cast(tuple[Any, ...], python_state))
        np.random.set_state(
            (
                str(numpy_state["bit_generator"]),
                np.asarray(numpy_state["state"], dtype=np.uint32),
                int(numpy_state["position"]),
                int(numpy_state["has_gauss"]),
                float(numpy_state["cached_gaussian"]),
            )
        )
        torch.set_rng_state(torch_cpu.cpu())
        if torch.cuda.is_available():
            if len(torch_cuda) != torch.cuda.device_count() or not all(
                isinstance(item, torch.Tensor) for item in torch_cuda
            ):
                raise RuntimeError("managed-spot checkpoint CUDA RNG device count differs")
            torch.cuda.set_rng_state_all(torch_cuda)
        elif torch_cuda:
            raise RuntimeError("managed-spot checkpoint requires CUDA RNG state without CUDA")
    except (TypeError, ValueError) as error:
        raise RuntimeError("managed-spot checkpoint RNG state cannot be restored") from error


def _write_resume_checkpoint(
    checkpoint_root: Path,
    *,
    model: CrossEncoder,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    config: ExperimentConfig,
    completed_epoch: int,
    optimizer_steps: int,
    best_epoch: int,
    stopper: EarlyStopper,
    elapsed_training_seconds: float,
    training_complete: bool,
    curves: list[CurvePoint],
) -> Path:
    """Commit a resumable epoch only after every model and optimizer file is durable locally."""

    checkpoint_root.mkdir(parents=True, exist_ok=True)
    target = checkpoint_root / f"epoch-{completed_epoch:04d}"
    staging = checkpoint_root / f".staging-{completed_epoch:04d}-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        model.save_pretrained(
            str(staging / "model"), create_model_card=False, safe_serialization=True
        )
        torch.save(
            {
                "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict(),
                "rng": _capture_rng_state(),
            },
            staging / "optimizer-state.pt",
        )
        state = {
            "schema_version": "1.0.0",
            "config_hash": config.config_hash,
            "dataset_manifest_hash": config.dataset_manifest_hash,
            "completed_epoch": completed_epoch,
            "optimizer_steps": optimizer_steps,
            "best_epoch": best_epoch,
            "best_validation_ndcg_at_10": stopper.best,
            "patience_reference": stopper.patience_reference,
            "bad_epochs": stopper.bad_epochs,
            "elapsed_training_seconds": elapsed_training_seconds,
            "training_complete": training_complete,
            "curves": [asdict(point) for point in curves],
        }
        (staging / "trainer-state.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest = {
            "schema_version": "1.0.0",
            "config_hash": config.config_hash,
            "dataset_manifest_hash": config.dataset_manifest_hash,
            "completed_epoch": completed_epoch,
            "files": _checkpoint_inventory(staging),
        }
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        manifest_path = staging / "checkpoint-manifest.json"
        manifest_path.write_text(manifest_text, encoding="utf-8")
        (staging / "COMPLETE").write_text(
            "sha256:" + _file_sha256(manifest_path) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def configure_determinism(seed: int, *, strict: bool) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(strict, warn_only=not strict)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False


def _resolve_training_device(requested: str) -> tuple[str, str, bool, int, str]:
    cuda_available = bool(torch.cuda.is_available())
    cuda_device_count = int(torch.cuda.device_count()) if cuda_available else 0
    if requested.startswith("cuda") and not cuda_available:
        raise RuntimeError("CUDA training was requested but CUDA is unavailable")
    selected = choose_device(requested)
    device_type = torch.device(selected).type
    if device_type not in {"cpu", "cuda", "mps"}:
        raise RuntimeError(f"unsupported training device type: {device_type}")
    if device_type == "cuda" and (not cuda_available or cuda_device_count < 1):
        raise RuntimeError("CUDA device selection has no available CUDA device")
    accelerator_type = "gpu" if device_type == "cuda" else "cpu"
    return selected, device_type, cuda_available, cuda_device_count, accelerator_type


def _early_stopping(config: ExperimentConfig) -> tuple[int, float]:
    value = config.early_stopping
    if isinstance(value, bool):
        return (2 if value else config.max_epochs + 1), 0.0
    return (
        (value.patience, value.min_delta)
        if value.enabled
        else (config.max_epochs + 1, value.min_delta)
    )


def _schedule_factor(step: int, *, warmup_steps: int, total_steps: int) -> float:
    if warmup_steps and step < warmup_steps:
        return (step + 1) / warmup_steps
    decay_steps = max(total_steps - warmup_steps, 1)
    return max((total_steps - step) / decay_steps, 0.0)


def _model(config: ExperimentConfig, device: str) -> CrossEncoder:
    return cast(
        CrossEncoder,
        CrossEncoder(
            config.base_model_id,
            revision=config.base_model_revision,
            trust_remote_code=False,
            max_length=config.max_sequence_length,
            num_labels=1,
            device=device,
        ),
    )


def _validation_metric(
    model: CrossEncoder,
    frame: pd.DataFrame,
    *,
    text_column: str,
    batch_size: int,
) -> float:
    pairs = [
        (str(row.query), str(getattr(row, text_column))) for row in frame.itertuples(index=False)
    ]
    predicted = _predict_array(
        model,
        pairs,
        batch_size=batch_size,
        show_progress_bar=False,
    )
    values = frame[["query_id", "product_id", "esci_label"]].copy()
    values["_score"] = predicted
    rankings: dict[str, list[str]] = {}
    for query_id, group in values.groupby("query_id", sort=True):
        order = rank_by_score(group["product_id"].astype(str).tolist(), group["_score"].tolist())
        rankings[str(query_id)] = group.iloc[order]["esci_label"].astype(str).tolist()
    aggregate = aggregate_query_metrics(rankings)
    value = aggregate.values["graded_ndcg@10"]
    if value is None:
        raise ValueError("validation set has no query with positive ideal DCG")
    return float(value)


def _precision(config: ExperimentConfig, device: str) -> tuple[bool, torch.dtype]:
    requested = config.precision
    if requested in {"bf16", "bfloat16"}:
        return True, torch.bfloat16
    if requested in {"fp16", "float16"} and device == "cuda":
        return True, torch.float16
    if requested == "auto" and device == "cuda":
        if torch.cuda.is_bf16_supported():
            return True, torch.bfloat16
        return True, torch.float16
    return False, torch.float32


def train_candidate(
    training_sample: pd.DataFrame,
    validation_frame: pd.DataFrame,
    config: ExperimentConfig,
    *,
    output_dir: str | Path,
    device: str = "auto",
    checkpoint_dir: str | Path | None = None,
) -> TrainingResult:
    required_train = {"query", "input_text", "target", "query_id", "project_split"}
    required_validation = {
        "query",
        "query_id",
        "product_id",
        "esci_label",
        "project_split",
        config.input_template_version.replace("enriched_v1", "text_enriched_v1").replace(
            "title_v1", "text_title_v1"
        ),
    }
    if missing := required_train - set(training_sample.columns):
        raise ValueError(f"training sample missing columns: {sorted(missing)}")
    if set(training_sample["project_split"].unique()) - {"train"}:
        raise ValueError("candidate training accepts training rows only")
    if set(validation_frame["project_split"].unique()) - {"validation"}:
        raise ValueError("checkpoint selection accepts validation rows only")
    text_column = (
        "text_title_v1" if config.input_template_version == "title_v1" else "text_enriched_v1"
    )
    required_validation.discard(config.input_template_version)
    required_validation.add(text_column)
    if missing := required_validation - set(validation_frame.columns):
        raise ValueError(f"validation frame missing columns: {sorted(missing)}")
    if set(training_sample["query_id"].astype(str)) & set(validation_frame["query_id"].astype(str)):
        raise ValueError("training and validation query IDs overlap")

    configure_determinism(config.seed, strict=config.deterministic_mode)
    (
        selected_device,
        device_type,
        cuda_available,
        cuda_device_count,
        accelerator_type,
    ) = _resolve_training_device(device)
    model = _model(config, selected_device)
    before = snapshot_parameters(model)
    checkpoint_root = Path(checkpoint_dir).expanduser().resolve() if checkpoint_dir else None
    resume = (
        _load_resume_checkpoint(checkpoint_root, config) if checkpoint_root is not None else None
    )
    if resume is not None:
        model = cast(
            CrossEncoder,
            CrossEncoder(
                str(resume.directory / "model"),
                device=selected_device,
                trust_remote_code=False,
            ),
        )
    transformer = model.model
    if transformer is None:
        raise RuntimeError("cross-encoder has no underlying transformer model")
    torch_model = cast(torch.nn.Module, transformer)
    torch_model.train()
    optimizer = torch.optim.AdamW(torch_model.parameters(), lr=config.learning_rate)
    loss_function = torch.nn.BCEWithLogitsLoss()
    micro_batch = config.effective_batch_size // config.gradient_accumulation_steps
    if (
        micro_batch < 1
        or micro_batch * config.gradient_accumulation_steps != config.effective_batch_size
    ):
        raise ValueError("effective batch size must be divisible by gradient accumulation steps")
    micro_batches_per_epoch = math.ceil(len(training_sample) / micro_batch)
    optimizer_steps_per_epoch = math.ceil(
        micro_batches_per_epoch / config.gradient_accumulation_steps
    )
    planned_optimizer_steps = optimizer_steps_per_epoch * config.max_epochs
    warmup_steps = round(planned_optimizer_steps * config.warmup_ratio)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lr_lambda=lambda step: _schedule_factor(
            step,
            warmup_steps=warmup_steps,
            total_steps=planned_optimizer_steps,
        ),
    )
    use_autocast, autocast_dtype = _precision(config, selected_device)
    patience, min_delta = _early_stopping(config)
    stopper = EarlyStopper(patience, min_delta)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    best_path = output / "best"
    curves: list[CurvePoint] = [] if resume is None else list(resume.curves)
    optimizer_steps = 0 if resume is None else resume.optimizer_steps
    best_epoch = 0 if resume is None else resume.best_epoch
    first_epoch = 1 if resume is None else resume.completed_epoch + 1
    elapsed_before_resume = 0.0 if resume is None else resume.elapsed_training_seconds
    training_complete = False if resume is None else resume.training_complete
    if resume is not None:
        state = torch.load(
            resume.directory / "optimizer-state.pt", map_location=selected_device, weights_only=True
        )
        if not isinstance(state, dict) or set(state) != {"optimizer", "scheduler", "rng"}:
            raise RuntimeError("managed-spot checkpoint optimizer state is malformed")
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        _restore_rng_state(state["rng"])
        stopper.best = resume.best_validation_ndcg_at_10
        stopper.patience_reference = resume.patience_reference
        stopper.bad_epochs = resume.bad_epochs
    start = time.perf_counter()

    for epoch in range(first_epoch, config.max_epochs + 1):
        if training_complete:
            break
        generator = torch.Generator().manual_seed(config.seed + epoch)
        indices = torch.randperm(len(training_sample), generator=generator).tolist()
        optimizer.zero_grad(set_to_none=True)
        cumulative_loss = 0.0
        batches = 0
        for offset in range(0, len(indices), micro_batch):
            batch = training_sample.iloc[indices[offset : offset + micro_batch]]
            encoded = model.tokenizer(
                batch["query"].astype(str).tolist(),
                batch["input_text"].astype(str).tolist(),
                padding=True,
                truncation=True,
                max_length=config.max_sequence_length,
                return_tensors="pt",
            ).to(selected_device)
            targets = torch.tensor(
                batch["target"].astype(float).tolist(), dtype=torch.float32, device=selected_device
            )
            with torch.autocast(
                device_type="cuda" if selected_device == "cuda" else "cpu",
                dtype=autocast_dtype,
                enabled=use_autocast,
            ):
                logits = transformer(**encoded).logits.reshape(-1).float()
                loss = loss_function(logits, targets) / config.gradient_accumulation_steps
            loss.backward()
            cumulative_loss += float(loss.detach().cpu()) * config.gradient_accumulation_steps
            batches += 1
            at_accumulation_boundary = (
                batches % config.gradient_accumulation_steps == 0
                or offset + micro_batch >= len(indices)
            )
            if at_accumulation_boundary:
                torch.nn.utils.clip_grad_norm_(torch_model.parameters(), max_norm=1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1

        torch_model.eval()
        validation_metric = _validation_metric(
            model,
            validation_frame,
            text_column=text_column,
            batch_size=micro_batch,
        )
        average_loss = cumulative_loss / max(batches, 1)
        curves.append(
            CurvePoint(
                epoch=epoch,
                optimizer_step=optimizer_steps,
                training_loss=average_loss,
                validation_ndcg_at_10=validation_metric,
            )
        )
        improved, should_stop = stopper.update(validation_metric)
        log_event(
            LOGGER,
            "training_epoch_complete",
            epoch=epoch,
            training_loss=average_loss,
            validation_ndcg_at_10=validation_metric,
            checkpoint_selected=improved,
            learning_rate=scheduler.get_last_lr()[0],
        )
        if improved:
            best_epoch = epoch
            if checkpoint_root is None:
                shutil.rmtree(best_path, ignore_errors=True)
                model.save_pretrained(
                    str(best_path), create_model_card=False, safe_serialization=True
                )
        training_complete = should_stop or epoch == config.max_epochs
        if checkpoint_root is not None:
            _write_resume_checkpoint(
                checkpoint_root,
                model=model,
                optimizer=optimizer,
                scheduler=scheduler,
                config=config,
                completed_epoch=epoch,
                optimizer_steps=optimizer_steps,
                best_epoch=best_epoch,
                stopper=stopper,
                elapsed_training_seconds=(elapsed_before_resume + time.perf_counter() - start),
                training_complete=training_complete,
                curves=curves,
            )
        if should_stop:
            break
        torch_model.train()

    if checkpoint_root is not None and best_epoch:
        durable_best = checkpoint_root / f"epoch-{best_epoch:04d}" / "model"
        shutil.rmtree(best_path, ignore_errors=True)
        shutil.copytree(durable_best, best_path)
    if not best_path.exists() or not math.isfinite(stopper.best):
        raise RuntimeError("training completed without a valid checkpoint")
    curves_path = write_curves(output / "curves.json", curves)
    fresh = load_checkpoint(best_path, device="cpu")
    changed = assert_any_parameter_changed(before, fresh)
    probe = training_sample.iloc[0]
    probe_pair = [(str(probe["query"]), str(probe["input_text"]))]
    reloaded = cast(
        CrossEncoder,
        CrossEncoder(str(best_path), device="cpu", trust_remote_code=False),
    )
    original_prediction = _predict_array(reloaded, probe_pair, show_progress_bar=False)
    fresh_prediction = _predict_array(fresh, probe_pair, show_progress_bar=False)
    fresh_verified = bool(np.allclose(original_prediction, fresh_prediction, atol=1e-7, rtol=0))
    if not fresh_verified:
        raise AssertionError("fresh checkpoint load changed the probe prediction")
    result = TrainingResult(
        best_checkpoint=str(best_path.resolve()),
        best_validation_ndcg_at_10=stopper.best,
        epochs_completed=len(curves),
        optimizer_steps=optimizer_steps,
        duration_seconds=elapsed_before_resume + time.perf_counter() - start,
        changed_parameter_count=len(changed),
        curves_path=str(curves_path.resolve()),
        fresh_load_verified=fresh_verified,
        warmup_steps=warmup_steps,
        planned_optimizer_steps=planned_optimizer_steps,
        device_type=device_type,
        cuda_available=cuda_available,
        cuda_device_count=cuda_device_count,
        accelerator_type=accelerator_type,
    )
    (output / "training-summary.json").write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
