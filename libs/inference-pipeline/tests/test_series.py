import numpy as np

from calotype_inference_pipeline.series import links, smooth, spread

SCENE_A = [0.2, 0.8, 0.1, 0.5]
SCENE_B = [0.9, 0.1, 0.7, 0.2]


def _burst(scene, start, count, jitter=0.01):
    rng = np.random.default_rng(int(start))
    feats = [list(np.array(scene) + rng.normal(0, jitter, len(scene))) for _ in range(count)]
    return feats, [start + i for i in range(count)]


def _shoot():
    """Two bursts of five frames, a minute apart, in two different scenes."""
    fa, ta = _burst(SCENE_A, 0.0, 5)
    fb, tb = _burst(SCENE_B, 60.0, 5)
    return fa + fb, ta + tb


def test_a_burst_is_linked_and_other_scenes_are_not():
    features, times = _shoot()
    pairs = {(i, j) for i, j, _ in links(features, times)}
    assert (0, 1) in pairs and (5, 6) in pairs
    assert not any(i < 5 <= j for i, j in pairs)


def test_photos_close_in_time_but_unlike_are_not_linked():
    features = [SCENE_A, SCENE_B, SCENE_A, SCENE_B]
    assert {(i, j) for i, j, _ in links(features, [0.0, 1.0, 2.0, 3.0])} == {(0, 2), (1, 3)}


def test_a_selection_that_is_one_single_burst_is_still_linked():
    features, times = _burst(SCENE_A, 0.0, 4)
    assert {k for i, j, _ in links(features, times) for k in (i, j)} == {0, 1, 2, 3}


def test_a_series_agrees_afterwards_and_keeps_its_mean():
    features, times = _shoot()
    exposures = [0.30, 0.55, 0.20, 0.60, 0.35, -0.40, -0.10, -0.55, -0.20, -0.35]
    values = [{"exposure": e, "contrast": 10.0 * i} for i, e in enumerate(exposures)]
    out = smooth(values, features, times)
    first, second = [v["exposure"] for v in out[:5]], [v["exposure"] for v in out[5:]]
    assert np.ptp(first) < 0.25 * np.ptp(exposures[:5])
    assert np.ptp(second) < 0.25 * np.ptp(exposures[5:])
    assert abs(np.mean(first) - np.mean(exposures[:5])) < 1e-9
    assert abs(np.mean(second) - np.mean(exposures[5:])) < 1e-9
    assert [v["contrast"] for v in out] == [v["contrast"] for v in values]
    assert values[0]["exposure"] == 0.30


def test_an_edited_example_stays_and_pulls_its_series():
    features, times = _shoot()
    values = [{"exposure": 0.0} for _ in range(10)]
    values[2] = {"exposure": 1.0}
    fixed = [i == 2 for i in range(10)]
    out = smooth(values, features, times, fixed)
    assert out[2]["exposure"] == 1.0
    assert all(0.5 < out[i]["exposure"] < 1.0 for i in (0, 1, 3, 4))
    assert all(out[i]["exposure"] == 0.0 for i in range(5, 10))


def test_photos_without_the_slider_take_no_part():
    features, times = _burst(SCENE_A, 0.0, 3)
    values = [{"exposure": 0.0, "temp": 5000.0}, {"exposure": 0.6}, {"exposure": 0.3, "temp": 5600.0}]
    out = smooth(values, features, times)
    assert "temp" not in out[1]
    assert 5000.0 < out[0]["temp"] < out[2]["temp"] < 5600.0


def test_without_capture_times_nothing_changes():
    features, _ = _shoot()
    values = [{"exposure": float(i)} for i in range(10)]
    assert smooth(values, features, None) == values


def test_spread_drops_after_smoothing():
    features, times = _shoot()
    values = [{"exposure": e} for e in [0.30, 0.55, 0.20, 0.60, 0.35, -0.40, -0.10, -0.55, -0.20, -0.35]]
    before = spread(values, features, times, "exposure")
    after = spread(smooth(values, features, times), features, times, "exposure")
    assert after < 0.3 * before
    assert spread(values, features, times, "temp") is None
