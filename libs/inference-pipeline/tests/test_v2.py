"""Feature version 2 and the versioned models."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from calotype_inference_pipeline import (
    FEATURE_DIM_V2,
    FEATURE_MODEL_VERSION,
    FEATURE_VERSION_V2,
    LR_PARAMS,
    artifact_feature_version,
    compute_features,
    run_inference,
    train_for_version,
)
from calotype_inference_pipeline.features_v2 import face_stats


def _jpeg(color=(120, 90, 60), size=(600, 400)) -> bytes:
    rng = np.random.default_rng(1)
    arr = (np.array(color) + rng.integers(-20, 20, (size[1], size[0], 3))).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG")
    return buf.getvalue()


def test_v2_vector_has_fixed_size_and_no_face_flag():
    v = compute_features(_jpeg(), FEATURE_VERSION_V2)
    assert len(v) == FEATURE_DIM_V2 == 153
    assert v[-5] == 0.0, "no face in a noise image"
    assert all(np.isfinite(v))


def test_v2_refuses_undecodable_images():
    with pytest.raises(ValueError):
        compute_features(b"not an image", FEATURE_VERSION_V2)


def test_face_stats_use_the_face_box():
    rgb = np.full((100, 100, 3), 40, np.uint8)
    rgb[20:60, 30:70] = 220                      # bright face on a dark background
    with_face = face_stats(rgb, (30, 20, 40, 40))
    without = face_stats(rgb, None)
    assert with_face[0] == 1.0 and without[0] == 0.0
    assert with_face[1] > 0.8 > without[1]


def _data(n, dim, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.random((n, dim))
    Y = [{p: float(2 * x[0] - 1) if p == "exposure" else 5000.0 + 1000 * x[1] if p == "temp" else 0.0
          for p in LR_PARAMS} for x in X]
    return X.tolist(), Y


@pytest.mark.parametrize("n,kind", [(10, "ridge_v2"), (120, "gbr_v2")])
def test_v2_models_learn_and_record_their_feature_version(n, kind):
    X, Y = _data(n, FEATURE_DIM_V2)
    model = train_for_version(X, Y, FEATURE_VERSION_V2)
    import joblib

    assert joblib.load(io.BytesIO(model))["type"] == kind
    assert artifact_feature_version(model) == FEATURE_VERSION_V2
    pred = run_inference(model, X[0])
    assert set(pred) == set(LR_PARAMS)
    if kind == "gbr_v2":
        Xt, Yt = _data(40, FEATURE_DIM_V2, seed=1)
        err = np.mean([abs(run_inference(model, x)["exposure"] - y["exposure"]) for x, y in zip(Xt, Yt)])
        assert err < 0.25, "boosting learns the exposure rule"


def test_wrong_vector_size_is_refused():
    X, Y = _data(40, FEATURE_DIM_V2)
    model = train_for_version(X, Y, FEATURE_VERSION_V2)
    with pytest.raises(ValueError, match="model expects 153"):
        run_inference(model, [0.0] * 128)


def test_v1_artifacts_report_v1():
    X, Y = _data(10, 128)
    assert artifact_feature_version(train_for_version(X, Y, FEATURE_MODEL_VERSION)) == FEATURE_MODEL_VERSION
