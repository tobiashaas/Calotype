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
    assert methods == {"exposure": "same", "contrast": "same"}


def test_per_photo_differences_are_learned_inside_the_shoot():
    X = _shoot(60, seed=1)
    exposure = 0.5 + 0.4 * X[:, 0]                     # brightness follows one feature
    truth = [{"exposure": float(e)} for e in exposure]
    model = [{"exposure": 0.0} for _ in exposure]       # the profile knows nothing about it
    out, methods = calibrate(truth[:30], model[:30], X[:30], model[30:], X[30:])
    err = np.abs(np.array([o["exposure"] for o in out]) - exposure[30:])
    assert methods["exposure"] == "blend"
    mean_err = np.abs(exposure[:30].mean() - exposure[30:])
    assert err.mean() < 0.75 * mean_err.mean()   # strongly regularised, but clearly better


def test_a_profile_that_explains_the_examples_is_used_as_a_feature():
    X = _shoot(60, seed=2)
    signal = np.random.default_rng(3).normal(size=60) * 300
    truth = [{"temp": 5200 + s} for s in signal]
    model = [{"temp": 4000 + s} for s in signal]        # right differences, wrong level
    out, methods = calibrate(truth[:20], model[:20], X[:20], model[20:], X[20:])
    assert methods["temp"] == "blend"
    wanted = np.array([t["temp"] for t in truth[20:]])
    error = np.mean(np.abs(np.array([o["temp"] for o in out]) - wanted))
    without, _ = calibrate(truth[:20], None, X[:20], None, X[20:])
    assert error < 0.6 * np.mean(np.abs(np.array([o["temp"] for o in without]) - wanted))
    assert abs(np.mean([o["temp"] for o in out]) - wanted.mean()) < 150     # the examples' level, not the profile's


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
    assert methods == {"exposure": "blend"}     # no profile: ridge + the examples closest in content
    error = np.mean([abs(o["exposure"] - e) for o, e in zip(out, exposure[30:])])
    assert error < 0.75 * np.mean(np.abs(exposure[30:] - exposure[:30].mean()))   # better than the mean
    out, _ = calibrate(truth[1:4], None, X[1:4], None, X[30:])   # few examples: their mean
    assert all(o["contrast"] == pytest.approx(10) for o in out)


def test_blend_follows_the_examples_closest_in_content():
    # Two kinds of photos (indoors / outdoors) with their own exposure: a photo takes the
    # value of the examples that look like it, not the shoot's mean.
    rng = np.random.default_rng(3)
    indoors = rng.normal(0.0, 0.05, (20, 6))
    outdoors = rng.normal(1.0, 0.05, (20, 6))
    X_ref = np.vstack([indoors[:10], outdoors[:10]])
    truth = [{"exposure": 1.0}] * 10 + [{"exposure": -0.5}] * 10
    out, methods = calibrate(truth, None, X_ref, None, np.vstack([indoors[10:], outdoors[10:]]))
    assert methods == {"exposure": "blend"}
    assert all(o["exposure"] > 0.6 for o in out[:10])
    assert all(o["exposure"] < -0.1 for o in out[10:])


def test_the_cameras_measured_light_helps_temperature_only():
    # The edited temperature follows what the camera measured; the image features say nothing.
    rng = np.random.default_rng(5)
    X = rng.normal(0, 1, (60, 12))
    measured = rng.uniform(3500, 7500, 60)
    truth = [{"temp": float(0.8 * m + 900), "exposure": 0.3} for m in measured]
    plain, _ = calibrate(truth[:30], None, X[:30], None, X[30:])
    lit, methods = calibrate(truth[:30], None, X[:30], None, X[30:], None, None, measured[:30], measured[30:])
    wanted = np.array([t["temp"] for t in truth[30:]])
    error = lambda out: np.mean(np.abs(np.array([o["temp"] for o in out]) - wanted))  # noqa: E731
    assert error(lit) < 0.5 * error(plain)
    assert methods["temp"] == "blend"
    assert [o["exposure"] for o in lit] == pytest.approx([o["exposure"] for o in plain])


def test_the_cameras_exposure_settings_help_exposure_only():
    # The edit lifts photos the more, the higher the ISO was; the image features say nothing.
    rng = np.random.default_rng(6)
    X = rng.normal(0, 1, (60, 12))
    camera = np.column_stack([rng.uniform(6.6, 12.6, 60), rng.uniform(-9, -4, 60), rng.uniform(0.5, 3, 60), np.zeros(60)])
    truth = [{"exposure": float(0.15 * (iso - 9.6)), "temp": 5500.0} for iso in camera[:, 0]]
    plain, _ = calibrate(truth[:30], None, X[:30], None, X[30:])
    lit, _ = calibrate(truth[:30], None, X[:30], None, X[30:], None, None, None, None, camera[:30], camera[30:])
    wanted = np.array([t["exposure"] for t in truth[30:]])
    error = lambda out: np.mean(np.abs(np.array([o["exposure"] for o in out]) - wanted))  # noqa: E731
    assert error(lit) < 0.7 * error(plain)
    assert [o["temp"] for o in lit] == pytest.approx([o["temp"] for o in plain])


def test_a_slider_most_examples_share_stays_exactly_there():
    # Contrast was synced over the shoot (+12), four photos got an own value; exposure varies.
    rng = np.random.default_rng(8)
    X = rng.normal(size=(40, 6))
    truth = [{"contrast": 12.0, "exposure": float(e)} for e in rng.normal(0.3, 0.3, 30)]
    for i in (3, 9, 17, 25):
        truth[i]["contrast"] = 40.0
    out, methods = calibrate(truth, None, X[:30], None, X[30:])
    assert methods == {"contrast": "same", "exposure": "blend"}
    assert all(o["contrast"] == 12.0 for o in out)
    truth[1]["contrast"] = truth[2]["contrast"] = truth[4]["contrast"] = truth[5]["contrast"] = 40.0
    truth[6]["contrast"] = truth[7]["contrast"] = truth[8]["contrast"] = 30.0     # now 19 of 30
    _, methods = calibrate(truth, None, X[:30], None, X[30:])
    assert methods["contrast"] == "blend"


def test_a_photo_close_in_time_to_an_edited_one_takes_its_values():
    rng = np.random.default_rng(9)
    X = rng.normal(size=(14, 6))
    contrast = rng.normal(10.0, 12.0, 10)
    truth = [{"contrast": float(c)} for c in contrast]
    times = [600.0 * i for i in range(10)]                    # one example every ten minutes
    new_times = [600.0 * 3 + 30, 600.0 * 7 - 90, 600.0 * 2 + 300, 99_999.0]
    out, methods = calibrate(truth, None, X[:10], None, X[10:], times, new_times)
    plain, _ = calibrate(truth, None, X[:10], None, X[10:])
    assert methods == {"contrast": "blend+scene"}
    assert out[0]["contrast"] == pytest.approx(contrast[3])   # 30 s after example 3
    assert out[1]["contrast"] == pytest.approx(contrast[7])   # 90 s before example 7
    assert out[2]["contrast"] == pytest.approx(plain[2]["contrast"])   # five minutes from any: blend
    assert out[3]["contrast"] == pytest.approx(plain[3]["contrast"])


def test_white_balance_follows_the_closest_edited_photo_for_ten_minutes():
    rng = np.random.default_rng(5)
    X = rng.normal(size=(13, 6))
    temp = rng.normal(5500.0, 600.0, 10)
    truth = [{"temp": float(t)} for t in temp]
    times = [3600.0 * i for i in range(10)]                   # one example every hour
    out, _ = calibrate(truth, None, X[:10], None, X[10:], times, [3600.0 * 4 + 500, 3600.0 * 6 - 590, 3600.0 * 2 + 700])
    plain, _ = calibrate(truth, None, X[:10], None, X[10:])
    assert out[0]["temp"] == pytest.approx(temp[4])           # eight minutes after example 4
    assert out[1]["temp"] == pytest.approx(temp[6])
    assert out[2]["temp"] == pytest.approx(plain[2]["temp"])  # more than ten minutes: blend


def test_exposure_of_the_closest_edited_photo_fades_with_the_time_between():
    rng = np.random.default_rng(9)
    X = rng.normal(size=(13, 6))
    exposure = rng.normal(0.4, 0.4, 10)
    truth = [{"exposure": float(e)} for e in exposure]
    times = [3600.0 * i for i in range(10)]
    out, _ = calibrate(truth, None, X[:10], None, X[10:], times, [3600.0 * 3, 3600.0 * 3 + 60, 3600.0 * 3 + 601])
    plain, _ = calibrate(truth, None, X[:10], None, X[10:])
    assert out[0]["exposure"] == pytest.approx(exposure[3])   # same moment: the example's value
    share = np.exp(-1.0)                                      # one minute later: 1/e of it
    assert out[1]["exposure"] == pytest.approx(share * exposure[3] + (1 - share) * plain[1]["exposure"])
    assert out[2]["exposure"] == pytest.approx(plain[2]["exposure"])


def test_a_slider_the_profile_does_not_predict_is_calibrated_from_the_examples_alone():
    rng = np.random.default_rng(4)
    X = rng.normal(size=(15, 6))
    truth = [{"exposure": 0.3 + 0.1 * i, "temp": 5000.0 + 40 * i} for i in range(10)]
    # The profile keeps the camera's white balance: its predictions carry no temperature.
    ref_model = [{"exposure": 0.2} for _ in range(10)]
    model = [{"exposure": 0.2} for _ in range(5)]
    out, methods = calibrate(truth, ref_model, X[:10], model, X[10:])
    assert set(methods) == {"exposure", "temp"}
    assert all("temp" in row and 4800 < row["temp"] < 5600 for row in out)
