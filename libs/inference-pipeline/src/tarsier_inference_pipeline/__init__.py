"""Tarsier inference pipeline — feature extraction and model training/inference."""

from __future__ import annotations

from tarsier_inference_pipeline.features import (
    FEATURE_DIM,
    FEATURE_MODEL_VERSION,
    LR_PARAMS,
    extract_features,
)
from tarsier_inference_pipeline.features_v2 import (
    FEATURE_DIM_V2,
    FEATURE_VERSION_V2,
    extract_features_v2,
)
from tarsier_inference_pipeline.model import (
    MIN_SAMPLES,
    artifact_feature_version,
    run_inference,
    train_model,
    train_model_v2,
)

# What new profiles are trained on. v1 stays computable for profiles trained before.
CURRENT_FEATURE_VERSION = FEATURE_VERSION_V2

_EXTRACTORS = {
    FEATURE_MODEL_VERSION: extract_features,
    FEATURE_VERSION_V2: extract_features_v2,
}
SUPPORTED_FEATURE_VERSIONS = tuple(_EXTRACTORS)


def compute_features(image_bytes: bytes, version: str = CURRENT_FEATURE_VERSION) -> list[float]:
    """Feature vector of the given version. v2 raises ValueError for undecodable images."""
    try:
        extractor = _EXTRACTORS[version]
    except KeyError:
        raise ValueError(f"unknown feature version {version!r}") from None
    return extractor(image_bytes)


def train_for_version(
    feature_vectors: list[list[float]], targets: list[dict[str, float]], version: str
) -> bytes:
    """v1 → Ridge as before; v2 → gradient boosting (Ridge for small sets)."""
    if version == FEATURE_MODEL_VERSION:
        return train_model(feature_vectors, targets)
    return train_model_v2(feature_vectors, targets, version)


__all__ = [
    "CURRENT_FEATURE_VERSION",
    "FEATURE_DIM",
    "FEATURE_DIM_V2",
    "FEATURE_MODEL_VERSION",
    "FEATURE_VERSION_V2",
    "LR_PARAMS",
    "MIN_SAMPLES",
    "SUPPORTED_FEATURE_VERSIONS",
    "artifact_feature_version",
    "compute_features",
    "extract_features",
    "extract_features_v2",
    "run_inference",
    "train_for_version",
    "train_model",
    "train_model_v2",
]
