"""scikit-learn Ridge regression model for LR parameter prediction."""

from __future__ import annotations

import io
from collections.abc import Sequence

import joblib
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler

from calotype_inference_pipeline.features import LR_PARAMS

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
# A slider this share of the training photos carry with the identical value belongs to the
# photographer's recipe: it is stored as a constant instead of being predicted. Measured on
# 30 of the maintainer's weddings: 85-100 % of a wedding's photos share contrast, highlights,
# shadows, whites and blacks exactly — only the exposure changes from photo to photo. A model
# over all ten sliders averaged three such recipes into values none of them has.
RECIPE_SHARE = 0.6
# White balance is never a recipe constant: a Kelvin value belongs to the light of one photo.
NEVER_CONSTANT = ("temp", "tint")
# From this share of training photos on the camera's white balance, the photographer's way is to
# leave it — unless the light calls for more: then the profile sets its own Kelvin.
AS_SHOT_SHARE = 0.3
# A prediction this close to the camera's Kelvin (in mired: ~500 K at 5900 K, ~180 K at 3500 K)
# keeps the camera's white balance. A hut lit by lamps (camera 5900 K, photographer 2850 K) is
# far outside it; daylight is inside.
AS_SHOT_MIRED = 15.0


def _present(rows: list[dict[str, float]], p: str) -> list[float]:
    return [float(row[p]) for row in rows if row.get(p) is not None]


def recipe_constants(rows: list[dict[str, float]]) -> dict[str, float]:
    """Sliders that at least ``RECIPE_SHARE`` of the rows carry with the identical value.

    A row without a slider (a value the photographer never decided, e.g. a preset's
    placeholder) does not count; a slider at most half of the rows decided is no constant."""
    out: dict[str, float] = {}
    for p in LR_PARAMS:
        present = _present(rows, p)
        if p in NEVER_CONSTANT or not present or len(present) * 2 < len(rows):
            continue
        values, counts = np.unique(np.round(present, 3), return_counts=True)
        if counts.max() / len(present) >= RECIPE_SHARE:
            out[p] = float(values[counts.argmax()])
    return out


def _as_shot_flags(as_shot: Sequence[bool] | bool, n: int) -> list[bool]:
    if isinstance(as_shot, bool):
        return [as_shot] * n
    flags = [bool(f) for f in as_shot]
    if len(flags) != n:
        raise ValueError(f"{len(flags)} as-shot flags for {n} training photos")
    return flags


def train_model_v2(
    feature_vectors: list[list[float]],
    lr_settings_list: list[dict[str, float]],
    feature_version: str,
    as_shot: Sequence[bool] | bool = False,
) -> bytes:
    """Gradient boosting per slider (falls back to Ridge for small sets).

    The artifact records the feature version it was trained on, so inference can refuse
    vectors of another version instead of silently predicting nonsense. Sliders of the
    photographer's recipe (``recipe_constants``) are stored as constants and win over the
    model.

    A row may leave sliders out — values the photographer never decided: each slider learns
    only from the rows that carry it. as_shot: per row, whether the photo kept the camera's
    white balance. Its Kelvin is still a target (the camera got that light right); at
    inference a prediction close to the camera's keeps the camera's white balance.
    """
    if len(feature_vectors) < MIN_SAMPLES:
        raise ValueError(f"need at least {MIN_SAMPLES} training photos")
    flags = _as_shot_flags(as_shot, len(feature_vectors))
    X = np.array(feature_vectors, dtype=np.float32)
    Y = np.array([[np.nan if row.get(p) is None else row[p] for p in LR_PARAMS] for row in lr_settings_list],
                 dtype=np.float32)
    have = ~np.isnan(Y)
    if len(X) < BOOSTING_MIN_SAMPLES:
        # Ridge fits all sliders at once: an undecided value becomes the slider's median.
        medians = np.array([np.nanmedian(Y[:, j]) if have[:, j].any() else 0.0 for j in range(len(LR_PARAMS))])
        scaler = StandardScaler().fit(X)
        reg = MultiOutputRegressor(Ridge(alpha=1.0), n_jobs=1).fit(scaler.transform(X), np.where(have, Y, medians))
        artifact = {"type": "ridge_v2", "scaler": scaler, "model": reg,
                    "untrained": [p for j, p in enumerate(LR_PARAMS) if not have[:, j].any()]}
    else:
        from sklearn.ensemble import HistGradientBoostingRegressor

        models, fallbacks = {}, {}
        for j, p in enumerate(LR_PARAMS):
            decided = have[:, j]
            n = int(decided.sum())
            if n >= BOOSTING_MIN_SAMPLES:
                models[p] = HistGradientBoostingRegressor(
                    max_iter=400, learning_rate=0.05, l2_regularization=1.0,
                    min_samples_leaf=max(5, min(20, n // 20)), random_state=0,
                ).fit(X[decided], Y[decided, j])
            elif n >= MIN_SAMPLES:
                fallbacks[p] = float(np.median(Y[decided, j]))
        artifact = {"type": "gbr_v2", "models": models, "fallbacks": fallbacks}
    camera_temps = [row["temp"] for row, f in zip(lr_settings_list, flags) if f and row.get("temp") is not None]
    artifact.update(
        lr_params=LR_PARAMS, feature_version=feature_version, n_features=X.shape[1], n_samples=len(X),
        constants=recipe_constants(lr_settings_list),
        as_shot_share=sum(flags) / len(flags),
        as_shot_temp=float(np.median(camera_temps)) if camera_temps else None,
    )
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
    from calotype_inference_pipeline.features import FEATURE_MODEL_VERSION

    return _load(model_bytes).get("feature_version", FEATURE_MODEL_VERSION)


def _mired(kelvin: float) -> float:
    return 1e6 / max(float(kelvin), 1.0)


def _keeps_cameras_white_balance(artifact: dict, out: dict[str, float], as_shot_temp: float | None) -> bool:
    if "as_shot_share" not in artifact:  # artifacts before the per-photo decision
        return bool(artifact.get("as_shot"))
    if artifact["as_shot_share"] < AS_SHOT_SHARE or "temp" not in out:
        return False
    camera = as_shot_temp if as_shot_temp is not None else artifact.get("as_shot_temp")
    return camera is not None and abs(_mired(out["temp"]) - _mired(camera)) <= AS_SHOT_MIRED


def run_inference(
    model_bytes: bytes, feature_vector: list[float], as_shot_temp: float | None = None,
) -> dict[str, float]:
    """Apply a trained model to a feature vector and return LR settings.

    Returns a dict of {param: value} — without temperature and tint when the photographer
    mostly keeps the camera's white balance and the predicted Kelvin is close to the camera's
    (``as_shot_temp``: this photo's as-shot Kelvin if known, else the training photos'), and
    without sliders the training photos never decided.

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
        out = {p: float(m.predict(X)[0]) for p, m in artifact["models"].items()}
        out.update(artifact.get("fallbacks") or {})
    else:
        pred = artifact["model"].predict(artifact["scaler"].transform(X))[0]  # ridge_v1 / ridge_v2
        untrained = set(artifact.get("untrained") or ())
        out = {p: float(v) for p, v in zip(params, pred) if p not in untrained}
    # The recipe wins over the model (artifacts before this field have none).
    out.update(artifact.get("constants") or {})
    if _keeps_cameras_white_balance(artifact, out, as_shot_temp):
        for p in NEVER_CONSTANT:
            out.pop(p, None)
    return out
