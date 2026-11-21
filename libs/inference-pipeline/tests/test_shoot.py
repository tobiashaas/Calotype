import numpy as np
import pytest

from calotype_inference_pipeline.shoot import calibrate


def _shoot(n, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 6))
    return X


def test_constant_look_comes_from_the_examples_not_the_model():
    X = _shoot(40)
    truth = [{"exposure": 0.6, "contrast": 12.0} for _ in range(40)]
    model = [{"exposure": -0.2, "contrast": 0.0} for _ in range(40)]
    out, methods = calibrate(truth[:10], model[:10], X[:10], model[10:], X[10:])
    assert all(o["exposure"] == pytest.approx(0.6) and o["contrast"] == pytest.approx(12) for o in out)
    assert methods == {"exposure": "mean", "contrast": "mean"}


def test_per_photo_differences_are_learned_inside_the_shoot():
    X = _shoot(60, seed=1)
    exposure = 0.5 + 0.4 * X[:, 0]                     # brightness follows one feature
    truth = [{"exposure": float(e)} for e in exposure]
    model = [{"exposure": 0.0} for _ in exposure]       # the profile knows nothing about it
    out, methods = calibrate(truth[:30], model[:30], X[:30], model[30:], X[30:])
    err = np.abs(np.array([o["exposure"] for o in out]) - exposure[30:])
    assert methods["exposure"] == "ridge"
    mean_err = np.abs(exposure[:30].mean() - exposure[30:])
    assert err.mean() < 0.75 * mean_err.mean()   # strongly regularised, but clearly better


def test_model_offsets_are_kept_when_they_explain_the_examples():
    X = _shoot(60, seed=2)
    signal = np.random.default_rng(3).normal(size=60) * 300
    truth = [{"temp": 5200 + s} for s in signal]
    model = [{"temp": 4000 + s} for s in signal]        # right differences, wrong level
    out, methods = calibrate(truth[:20], model[:20], X[:20], model[20:], X[20:])
    assert methods["temp"] == "model"
    assert np.allclose([o["temp"] for o in out], [t["temp"] for t in truth[20:]])


def test_few_examples_use_their_mean_and_missing_sliders_keep_the_model():
    X = _shoot(5)
    truth = [{"exposure": 1.0}, {"exposure": 0.5}]
    model = [{"exposure": 0.0, "temp": 5000.0} for _ in range(5)]
    out, methods = calibrate(truth, model[:2], X[:2], model[2:], X[2:])
    assert methods == {"exposure": "mean"}
    assert [o["exposure"] for o in out] == [0.75] * 3
    assert [o["temp"] for o in out] == [5000.0] * 3


def test_needs_examples():
    with pytest.raises(ValueError):
        calibrate([], [], [], [{"exposure": 0.0}], [[0.0]])


def test_without_a_profile_the_examples_alone_set_the_look():
    X = _shoot(60, seed=1)
    exposure = 0.5 + 0.4 * X[:, 0]
    truth = [{"exposure": float(e), "contrast": 10.0} for e in exposure]
    truth[0].pop("contrast")   # a slider one example lacks gets no value at all
    out, methods = calibrate(truth[:30], None, X[:30], None, X[30:])
    assert len(out) == 30 and all("contrast" not in o for o in out)
    assert methods == {"exposure": "ridge"}
    out, _ = calibrate(truth[1:4], None, X[1:4], None, X[30:])   # few examples: their mean
    assert all(o["contrast"] == pytest.approx(10) for o in out)
