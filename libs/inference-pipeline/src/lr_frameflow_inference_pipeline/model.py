"""scikit-learn Ridge regression model for LR parameter prediction."""

from __future__ import annotations

import io

import joblib
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler

from lr_frameflow_inference_pipeline.features import LR_PARAMS

MIN_SAMPLES = 3
_MIN_SAMPLES = MIN_SAMPLES  # backwards-compatible alias


def train_model(
    feature_vectors: list[list[float]],
    lr_settings_list: list[dict[str, float]],
) -> bytes:
    """Train a MultiOutputRegressor(Ridge) on feature vectors and LR settings.

    Args:
        feature_vectors: list of N feature vectors (each 128 floats)
        lr_settings_list: list of N dicts with LR param values

    Returns:
        Serialized model as bytes (joblib format).
        If fewer than _MIN_SAMPLES samples, returns a zero-model sentinel.
    """
    if len(feature_vectors) < _MIN_SAMPLES:
        sentinel = {"type": "zero_model", "lr_params": LR_PARAMS}
        buf = io.BytesIO()
        joblib.dump(sentinel, buf)
        return buf.getvalue()

    X = np.array(feature_vectors, dtype=np.float32)
    Y = np.array(
        [[row.get(p, 0.0) for p in LR_PARAMS] for row in lr_settings_list],
        dtype=np.float32,
    )

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    reg = MultiOutputRegressor(Ridge(alpha=1.0), n_jobs=1)
    reg.fit(X_scaled, Y)

    artifact = {"type": "ridge_v1", "scaler": scaler, "model": reg, "lr_params": LR_PARAMS}
    buf = io.BytesIO()
    joblib.dump(artifact, buf)
    return buf.getvalue()


def run_inference(model_bytes: bytes, feature_vector: list[float]) -> dict[str, float]:
    """Apply a trained model to a feature vector and return LR settings.

    Returns a dict of {param: value} for all LR_PARAMS.

    Raises ``ValueError`` for an unreadable artifact: silently returning zeros would
    reset the user's photos to neutral settings.
    """
    try:
        artifact = joblib.load(io.BytesIO(model_bytes))
    except Exception as exc:
        raise ValueError("model artifact cannot be loaded") from exc

    if not isinstance(artifact, dict):
        raise ValueError("model artifact has an unexpected format")

    if artifact.get("type") == "zero_model":
        return {p: 0.0 for p in LR_PARAMS}

    scaler = artifact["scaler"]
    model = artifact["model"]
    params = artifact["lr_params"]

    X = np.array([feature_vector], dtype=np.float32)
    X_scaled = scaler.transform(X)
    pred = model.predict(X_scaled)[0]  # shape (n_params,)

    return {p: float(v) for p, v in zip(params, pred)}
