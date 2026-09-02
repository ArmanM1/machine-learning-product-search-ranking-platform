"""Dataset acquisition and deterministic preparation."""

from .download import acquire_dataset
from .io import load_dataset_manifest, load_prepared_split, resolve_manifest_path
from .normalize import NORMALIZATION_VERSION, normalize_text
from .settings import DataPreparationConfig, load_data_config
from .split import assign_train_validation, development_query_ids, sorted_id_hash

__all__ = [
    "NORMALIZATION_VERSION",
    "DataPreparationConfig",
    "acquire_dataset",
    "assign_train_validation",
    "development_query_ids",
    "load_data_config",
    "load_dataset_manifest",
    "load_prepared_split",
    "normalize_text",
    "resolve_manifest_path",
    "sorted_id_hash",
]
