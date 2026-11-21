from uuid import uuid4

import pytest

from calotype_inference_worker.cli import smooth_series

EDITED = {"WhiteBalance": "Custom", "Temperature": 5600, "Tint": 4, "Exposure2012": 1.0}
UNTOUCHED = {"WhiteBalance": "As Shot", "Temperature": 5000, "Tint": 0, "Exposure2012": 0}


def _burst(count):
    ids = [uuid4() for _ in range(count)]
    vectors = {p: [0.5 + 0.001 * i, 0.2, 0.9] for i, p in enumerate(ids)}
    times = {p: float(i) for i, p in enumerate(ids)}
    return ids, vectors, times


def test_targets_of_a_burst_agree_and_the_example_stays_fixed():
    ids, vectors, times = _burst(4)
    settings = {ids[0]: dict(EDITED), **{p: dict(UNTOUCHED) for p in ids[1:]}}
    predictions = {p: {"exposure": e, "temp": 5200.0, "tint": 0.0}
                   for p, e in zip(ids, [0.0, 0.2, 0.6, 0.4])}
    assert smooth_series(predictions, vectors, settings, ids[1:], "raw", uuid4(), times)
    exposures = [predictions[p]["exposure"] for p in ids[1:]]
    assert max(exposures) - min(exposures) < 0.4
    assert all(e > 0.4 for e in exposures)           # pulled towards the edited +1.0
    assert predictions[ids[0]]["exposure"] == 0.0    # the example itself gets no new value
    assert all(predictions[p]["temp"] > 5200.0 for p in ids[1:])


def test_an_example_still_on_as_shot_white_balance_does_not_anchor_it():
    ids, vectors, times = _burst(3)
    settings = {ids[0]: {**UNTOUCHED, "Exposure2012": 1.0}, ids[1]: dict(UNTOUCHED), ids[2]: dict(UNTOUCHED)}
    predictions = {p: {"exposure": 0.0, "temp": 5600.0, "tint": 0.0} for p in ids}
    smooth_series(predictions, vectors, settings, ids[1:], "raw", uuid4(), times)
    assert all(predictions[p]["temp"] == pytest.approx(5600.0) for p in ids[1:])


def test_without_capture_times_nothing_is_smoothed():
    ids, vectors, times = _burst(3)
    times[ids[1]] = None
    predictions = {p: {"exposure": float(i)} for i, p in enumerate(ids)}
    before = {p: dict(v) for p, v in predictions.items()}
    assert not smooth_series(predictions, vectors, {p: dict(UNTOUCHED) for p in ids}, ids, "raw", uuid4(), times)
    assert predictions == before
