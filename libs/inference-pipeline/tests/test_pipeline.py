"""Tests for the inference-pipeline library (features + model)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from calotype_inference_pipeline import (
    FEATURE_DIM,
    LR_PARAMS,
    extract_features,
    run_inference,
    train_model,
)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _make_jpeg(color: tuple[int, int, int] = (128, 64, 32)) -> bytes:
    arr = np.full((64, 64, 3), color, dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_extract_features_dim():
    features = extract_features(_make_jpeg())
    assert len(features) == FEATURE_DIM


def test_extract_features_normalized():
    features = extract_features(_make_jpeg())
    r_sum = sum(features[0:32])
    g_sum = sum(features[32:64])
    b_sum = sum(features[64:96])
    v_sum = sum(features[96:128])
    for s in (r_sum, g_sum, b_sum, v_sum):
        assert abs(s - 1.0) < 0.01, f"histogram not normalized: sum={s}"


def test_extract_features_fallback_on_invalid_bytes():
    features = extract_features(b"not-a-jpeg")
    assert len(features) == FEATURE_DIM
    assert all(f == 0.0 for f in features)


def test_extract_features_fallback_on_empty_bytes():
    features = extract_features(b"")
    assert all(f == 0.0 for f in features)


# ---------------------------------------------------------------------------
# Model training + inference
# ---------------------------------------------------------------------------

def _make_training_data(n: int):
    rng = np.random.default_rng(42)
    vectors = rng.random((n, FEATURE_DIM)).tolist()
    settings = [{p: float(rng.uniform(-1, 1)) for p in LR_PARAMS} for _ in range(n)]
    return vectors, settings


def test_train_model_returns_bytes():
    vecs, settings = _make_training_data(5)
    model_bytes = train_model(vecs, settings)
    assert isinstance(model_bytes, bytes)
    assert len(model_bytes) > 0


def test_run_inference_returns_all_params():
    vecs, settings = _make_training_data(5)
    model_bytes = train_model(vecs, settings)
    result = run_inference(model_bytes, vecs[0])
    assert set(result.keys()) == set(LR_PARAMS)
    assert all(isinstance(v, float) for v in result.values())


def test_zero_model_fallback_below_min_samples():
    vecs, settings = _make_training_data(2)  # < 3 → zero model
    model_bytes = train_model(vecs, settings)
    result = run_inference(model_bytes, vecs[0])
    assert all(v == 0.0 for v in result.values())


def test_run_inference_invalid_bytes_raises():
    # Zeros would silently reset the user's photos — a broken artifact must fail loudly.
    with pytest.raises(ValueError):
        run_inference(b"garbage", [0.0] * FEATURE_DIM)


def test_train_inference_roundtrip_not_all_zero():
    """With enough samples the model should predict non-trivial values."""
    vecs, settings = _make_training_data(20)
    model_bytes = train_model(vecs, settings)
    result = run_inference(model_bytes, vecs[0])
    # At least one param should be non-zero given random LR targets.
    assert any(v != 0.0 for v in result.values())
