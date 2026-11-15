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


def test_capture_time_from_lightroom_and_folder_mode():
    from calotype_inference_worker.cli import capture_time

    a = capture_time({"date_time_original": "2022-03-19T14:05:33"})
    b = capture_time({"date_time_original": "2022-03-19T14:05:43.25+01:00"})
    assert b - a == 10
    assert capture_time({}) is None and capture_time(None) is None
    assert capture_time({"date_time_original": "garbage"}) is None


def test_series_follows_the_closest_edited_photo_in_time():
    ids, settings, predictions, vectors = _job([0.0] * 10, untouched=2)
    # Two scenes: examples 0-4 in the morning (exposure 0.2), 5-9 in the evening (1.2).
    for i, p in enumerate(ids[:10]):
        settings[p]["Exposure2012"] = 0.2 if i < 5 else 1.2
    times = {p: (i % 5 if i < 5 else 36000 + i) for i, p in enumerate(ids[:10])}
    times[ids[10]], times[ids[11]] = 2.5, 36007.5
    targets = calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4(), times)
    assert targets == ids[10:]
    assert predictions[ids[10]]["exposure"] == 0.2
    assert predictions[ids[11]]["exposure"] == 1.2


def test_without_a_profile_only_the_edited_sliders_are_set():
    import pytest

    ids, settings, predictions, vectors = _job([0.5, 0.7], untouched=3)
    empty = {p: {} for p in predictions}
    targets = calibrate_to_shoot(empty, vectors, settings, ids, "raw", uuid4(), with_model=False)
    assert targets == ids[2:]
    for p in targets:
        assert empty[p]["exposure"] == 0.6 and empty[p]["contrast"] == 10
        assert "temp" not in empty[p]   # RAW as shot: no Kelvin to copy, so none is invented
    none_edited = _job([], untouched=3)
    with pytest.raises(ValueError, match="no edited photos"):
        calibrate_to_shoot({p: {} for p in none_edited[0]}, none_edited[3], none_edited[1],
                           none_edited[0], "raw", uuid4(), with_model=False)


def test_the_shoots_look_comes_from_the_edited_photos():
    from calotype_inference_worker.cli import examples_look

    ids, settings, predictions, vectors = _job([0.5, 0.7, 0.6], untouched=2)
    for p in ids[:3]:
        settings[p].update({"Glow": 45, "GlowStyle": 2, "ColorGradeMidtoneHue": 30})
    targets = calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4())
    look = examples_look(predictions, targets, settings)
    assert look == {"Glow": 45, "GlowStyle": 2, "ColorGradeMidtoneHue": 30}
    assert examples_look(predictions, list(predictions), settings) == {}   # no examples, no look


def test_the_shoots_mask_strengths_come_from_the_edited_photos():
    from calotype_inference_worker.cli import examples_masks

    ids, settings, predictions, vectors = _job([0.5, 0.7, 0.6], untouched=2)
    subject = {"What": "Mask/Image", "MaskSubType": 1, "MaskBlendMode": 0}
    for p, shadows in zip(ids[:3], [0.1, 0.2, 0.3]):
        settings[p]["MaskGroupBasedCorrections"] = [
            {"CorrectionAmount": 1, "CorrectionMasks": [subject], "LocalShadows2012": shadows}]
    # an untouched photo with a mask is no example
    settings[ids[3]]["MaskGroupBasedCorrections"] = [
        {"CorrectionAmount": 1, "CorrectionMasks": [subject], "LocalShadows2012": -0.9}]
    targets = calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4())
    assert examples_masks(predictions, targets, settings) == {"subject": {"LocalShadows2012": 0.2}}
