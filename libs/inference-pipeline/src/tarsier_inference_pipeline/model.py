"""scikit-learn Ridge regression model for LR parameter prediction."""

from __future__ import annotations

import io

import joblib
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler

from tarsier_inference_pipeline.features import LR_PARAMS

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


BOOSTING_MIN_SAMPLES = 30  # below this, boosting overfits; Ridge on the same features is safer


def train_model_v2(
    feature_vectors: list[list[float]],
    lr_settings_list: list[dict[str, float]],
    feature_version: str,
) -> bytes:
    """Gradient boosting per slider (falls back to Ridge for small sets).

    The artifact records the feature version it was trained on, so inference can refuse
    vectors of another version instead of silently predicting nonsense.
    """
    if len(feature_vectors) < MIN_SAMPLES:
        raise ValueError(f"need at least {MIN_SAMPLES} training photos")
    X = np.array(feature_vectors, dtype=np.float32)
    Y = np.array([[row.get(p, 0.0) for p in LR_PARAMS] for row in lr_settings_list], dtype=np.float32)
    if len(X) < BOOSTING_MIN_SAMPLES:
        scaler = StandardScaler().fit(X)
        reg = MultiOutputRegressor(Ridge(alpha=1.0), n_jobs=1).fit(scaler.transform(X), Y)
        artifact = {"type": "ridge_v2", "scaler": scaler, "model": reg}
    else:
        from sklearn.ensemble import HistGradientBoostingRegressor

        leaf = max(5, min(20, len(X) // 20))
        models = {}
        for j, p in enumerate(LR_PARAMS):
            models[p] = HistGradientBoostingRegressor(
                max_iter=400, learning_rate=0.05, l2_regularization=1.0,
                min_samples_leaf=leaf, random_state=0,
            ).fit(X, Y[:, j])
        artifact = {"type": "gbr_v2", "models": models}
    artifact.update(lr_params=LR_PARAMS, feature_version=feature_version, n_features=X.shape[1],
                    n_samples=len(X))
    buf = io.BytesIO()
    joblib.dump(artifact, buf)
    return buf.getvalue()


def _load(model_bytes: bytes) -> dict:
    try:
        artifact = joblib.load(io.BytesIO(model_bytes))
    except Exception as exc:
        raise ValueError("model artifact cannot be loaded") from exc
    if not isinstance(artifact, dict):
        raise ValueError("model artifact has an unexpected format")
    return artifact


def artifact_feature_version(model_bytes: bytes) -> str:
    """Feature version a model expects (v1 artifacts predate the field)."""
    from tarsier_inference_pipeline.features import FEATURE_MODEL_VERSION

    return _load(model_bytes).get("feature_version", FEATURE_MODEL_VERSION)


def run_inference(model_bytes: bytes, feature_vector: list[float]) -> dict[str, float]:
    """Apply a trained model to a feature vector and return LR settings.

    Returns a dict of {param: value} for all LR_PARAMS.

    Raises ``ValueError`` for an unreadable artifact or a vector of the wrong size:
    silently returning zeros would reset the user's photos to neutral settings.
    """
    artifact = _load(model_bytes)
    kind = artifact.get("type")
    if kind == "zero_model":
        return {p: 0.0 for p in LR_PARAMS}

    expected = artifact.get("n_features")
    if expected is not None and len(feature_vector) != expected:
        raise ValueError(
            f"feature vector has {len(feature_vector)} values, model expects {expected} "
            f"({artifact.get('feature_version')})"
        )
    params = artifact["lr_params"]
    X = np.array([feature_vector], dtype=np.float32)
    if kind == "gbr_v2":
        return {p: float(artifact["models"][p].predict(X)[0]) for p in params}
    pred = artifact["model"].predict(artifact["scaler"].transform(X))[0]  # ridge_v1 / ridge_v2
    return {p: float(v) for p, v in zip(params, pred)}
