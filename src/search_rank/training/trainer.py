"""Deterministic pointwise cross-encoder fine-tuning entry point."""

from __future__ import annotations

import json
import logging
import math
import random
import shutil
import time
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


def configure_determinism(seed: int, *, strict: bool) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(strict, warn_only=not strict)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False


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
    selected_device = choose_device(device)
    model = _model(config, selected_device)
    before = snapshot_parameters(model)
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
    curves: list[CurvePoint] = []
    optimizer_steps = 0
    start = time.perf_counter()

    for epoch in range(1, config.max_epochs + 1):
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
            shutil.rmtree(best_path, ignore_errors=True)
            model.save_pretrained(str(best_path), create_model_card=False, safe_serialization=True)
        if should_stop:
            break
        torch_model.train()

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
        duration_seconds=time.perf_counter() - start,
        changed_parameter_count=len(changed),
        curves_path=str(curves_path.resolve()),
        fresh_load_verified=fresh_verified,
        warmup_steps=warmup_steps,
        planned_optimizer_steps=planned_optimizer_steps,
    )
    (output / "training-summary.json").write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
