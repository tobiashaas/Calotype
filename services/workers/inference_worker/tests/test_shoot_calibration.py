from uuid import uuid4

from calotype_inference_worker.cli import calibrate_to_shoot

UNTOUCHED = {"WhiteBalance": "As Shot", "Temperature": 5000, "Tint": 0, "Exposure2012": 0}


def _job(edited_exposures, untouched):
    ids = [uuid4() for _ in range(len(edited_exposures) + untouched)]
    settings = {}
    for pid, e in zip(ids, edited_exposures):
        settings[pid] = {**UNTOUCHED, "Exposure2012": e, "Contrast2012": 10}
    for pid in ids[len(edited_exposures):]:
        settings[pid] = dict(UNTOUCHED)
    predictions = {p: {"exposure": -1.0, "contrast": 0.0, "temp": 5000.0, "tint": 0.0} for p in ids}
    vectors = {p: [float(i), 1.0] for i, p in enumerate(ids)}
    return ids, settings, predictions, vectors


def test_edited_photos_set_the_look_and_get_no_result():
    ids, settings, predictions, vectors = _job([0.5, 0.7], untouched=3)
    targets = calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4())
    assert targets == ids[2:]
    for p in targets:
        assert predictions[p]["exposure"] == 0.6
        assert predictions[p]["contrast"] == 10


def test_without_edited_photos_every_prediction_stays():
    ids, settings, predictions, vectors = _job([], untouched=4)
    assert calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4()) == ids
    assert all(predictions[p]["exposure"] == -1.0 for p in ids)


def test_photos_without_features_are_neither_examples_nor_targets():
    ids, settings, predictions, vectors = _job([0.5, 0.7], untouched=2)
    del predictions[ids[0]], predictions[ids[3]]
    targets = calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4())
    assert targets == [ids[2]]
    assert predictions[ids[2]]["exposure"] == 0.7
