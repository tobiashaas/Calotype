"""A profile keeps the photographer's recipe: sliders most training photos share stay constant,
and the camera's white balance stays where the light is what the camera expected."""

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


def _hut_wedding(n: int = 80, seed: int = 5):
    """Camera fixed at 5899 K. Daylight photos stay as shot; under the hut's lamps (feature 1
    high) the photographer sets ~2850 K. Highlights: -100 is the import preset's placeholder."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 153))
    rows, as_shot = [], []
    for i in range(n):
        hut = i % 4 == 0
        X[i, 1] = 3.0 if hut else -1.0
        rows.append({"exposure": float(0.4 * X[i, 0]), "temp": 2850.0 if hut else 5899.0,
                     "tint": -21.0 if hut else 3.0, "contrast": -36.0, "shadows": 45.0,
                     "highlights": -100.0 if i % 2 else float(-40 + 10 * X[i, 2])})
        as_shot.append(not hut)
    return X.tolist(), rows, as_shot


# The hut photos (every fourth) were taken in the evening, minutes apart; daylight in the afternoon.
HUT_EVENING, AFTERNOON = 72_000.0, 50_000.0


def _times(n: int = 80) -> list[float]:
    return [HUT_EVENING + 60 * i if i % 4 == 0 else AFTERNOON + 30 * i for i in range(n)]


def test_daylight_keeps_the_cameras_white_balance_and_the_hut_gets_its_kelvin():
    X, rows, as_shot = _hut_wedding()
    model = train_for_version(X, rows, VERSION, as_shot=as_shot, capture_times=_times())
    daylight = run_inference(model, X[1], as_shot_temp=5899.0, capture_time=AFTERNOON + 30)
    hut = run_inference(model, X[0], as_shot_temp=5899.0, capture_time=HUT_EVENING + 90)
    assert "temp" not in daylight and "tint" not in daylight
    assert abs(hut["temp"] - 2850) < 300 and hut["tint"] < -10


def test_light_the_profile_never_saw_corrected_keeps_the_cameras_white_balance():
    """Measured on three unseen weddings: a predicted Kelvin for unseen light is mostly wrong."""
    X, rows, as_shot = _hut_wedding()
    model = train_for_version(X, rows, VERSION, as_shot=as_shot, capture_times=_times())
    another_wedding = run_inference(model, X[0], as_shot_temp=5899.0, capture_time=HUT_EVENING + 86_400 * 30)
    no_time = run_inference(model, X[0], as_shot_temp=5899.0)
    assert "temp" not in another_wedding and "temp" not in no_time


def test_a_profile_trained_without_capture_times_keeps_the_cameras_white_balance():
    X, rows, as_shot = _hut_wedding()
    out = run_inference(train_for_version(X, rows, VERSION, as_shot=as_shot), X[0], capture_time=HUT_EVENING)
    assert "temp" not in out


def test_a_photographer_who_sets_white_balance_everywhere_gets_it_predicted():
    X, rows, _ = _hut_wedding()
    out = run_inference(train_for_version(X, rows, VERSION, as_shot=False), X[1])
    assert "temp" in out


def test_a_placeholder_left_out_of_the_targets_is_not_learned():
    X, rows, as_shot = _hut_wedding()
    decided = [{k: v for k, v in r.items() if not (k == "highlights" and v == -100.0)} for r in rows]
    # X[1] is one of the photos that still carry the placeholder
    with_placeholder = run_inference(train_for_version(X, rows, VERSION, as_shot=as_shot), X[1])
    without = run_inference(train_for_version(X, decided, VERSION, as_shot=as_shot), X[1])
    assert with_placeholder["highlights"] < -90      # the preset was learned
    assert -70 < without["highlights"] < -10         # the photographer's range was learned
    assert "highlights" not in recipe_constants(decided)


def test_a_slider_no_photo_decided_is_not_predicted():
    X, rows, as_shot = _hut_wedding(n=20)  # small set: Ridge
    rows = [{k: v for k, v in r.items() if k != "highlights"} for r in rows]
    out = run_inference(train_for_version(X, rows, VERSION, as_shot=as_shot), X[1])
    assert "highlights" not in out and "exposure" in out


def test_an_artifact_from_before_keeps_its_as_shot_flag():
    import io

    import joblib

    from calotype_inference_pipeline.model import _load
    X, rows = _shoot()
    artifact = _load(train_for_version(X, rows, VERSION))
    for key in ("as_shot_share", "as_shot_temp"):
        artifact.pop(key)
    artifact["as_shot"] = True
    buf = io.BytesIO()
    joblib.dump(artifact, buf)
    out = run_inference(buf.getvalue(), X[0])
    assert "temp" not in out and "tint" not in out
