"""A profile keeps the photographer's recipe: sliders most training photos share stay constant,
and the camera's white balance stays when the training photos kept it."""

import numpy as np

from calotype_inference_pipeline import train_for_version
from calotype_inference_pipeline.model import recipe_constants, run_inference

VERSION = "histstats-face-v2"


def _shoot(n: int = 60, seed: int = 3):
    """A recipe (contrast, highlights, shadows fixed) with exposure following the brightness."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 153)).astype(float)
    rows = []
    for i in range(n):
        rows.append({
            "exposure": float(0.4 * X[i, 0]), "temp": float(5200 + 300 * X[i, 1]), "tint": float(4 + X[i, 2]),
            "contrast": 4.0, "highlights": -53.0, "shadows": 42.0, "whites": 38.0,
            # one photo in ten gets blacks of its own
            "blacks": -20.0 if i % 10 == 0 else 0.0, "vibrance": 0.0, "saturation": -16.0,
        })
    return X.tolist(), rows


def test_sliders_most_photos_share_are_the_recipe():
    _, rows = _shoot()
    constants = recipe_constants(rows)
    assert constants == {"contrast": 4.0, "highlights": -53.0, "shadows": 42.0, "whites": 38.0,
                         "blacks": 0.0, "vibrance": 0.0, "saturation": -16.0}
    assert "exposure" not in constants      # changes from photo to photo
    assert "temp" not in constants          # white balance is never a recipe constant


def test_a_slider_few_photos_share_is_not_a_constant():
    rows = [{"contrast": 4.0 if i < 5 else float(i)} for i in range(20)]
    assert "contrast" not in recipe_constants(rows)


def test_the_recipe_wins_over_the_model_and_exposure_is_still_predicted():
    X, rows = _shoot()
    model = train_for_version(X, rows, VERSION)
    out = run_inference(model, X[0])
    assert out["contrast"] == 4.0 and out["highlights"] == -53.0 and out["whites"] == 38.0
    assert out["blacks"] == 0.0             # not the mean of 0 and -20
    bright, dark = np.zeros(153), np.zeros(153)
    bright[0], dark[0] = 2.0, -2.0
    assert run_inference(model, bright.tolist())["exposure"] > run_inference(model, dark.tolist())["exposure"]
    assert "temp" in out                    # without as_shot the white balance is predicted


def test_a_profile_from_photos_on_the_cameras_white_balance_predicts_none():
    X, rows = _shoot()
    out = run_inference(train_for_version(X, rows, VERSION, as_shot=True), X[0])
    assert "temp" not in out and "tint" not in out
    assert "exposure" in out and out["contrast"] == 4.0
