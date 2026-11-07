"""Model registry — lives in the inference pipeline (both libraries use YuNet); re-exported."""

from lr_frameflow_inference_pipeline.models import MODELS, ModelFile, model_dir, model_path

__all__ = ["MODELS", "ModelFile", "model_dir", "model_path"]
