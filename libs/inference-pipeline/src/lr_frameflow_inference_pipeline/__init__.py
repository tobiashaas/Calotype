"""LR-FrameFlow inference pipeline — feature extraction and model training/inference."""

from __future__ import annotations

from lr_frameflow_inference_pipeline.features import (
    FEATURE_DIM,
    FEATURE_MODEL_VERSION,
    LR_PARAMS,
    extract_features,
)
from lr_frameflow_inference_pipeline.model import MIN_SAMPLES, run_inference, train_model

__all__ = [
    "FEATURE_DIM",
    "FEATURE_MODEL_VERSION",
    "LR_PARAMS",
    "MIN_SAMPLES",
    "extract_features",
    "train_model",
    "run_inference",
]
