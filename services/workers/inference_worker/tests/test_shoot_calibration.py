from uuid import uuid4

import pytest

from calotype_inference_worker.cli import calibrate_to_shoot, camera_exposure, measured_light

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


def test_a_look_chosen_for_the_job_replaces_the_profiles():
    from calotype_edit_serializer import apply_style
    from calotype_inference_worker.cli import job_preset

    profile = {"GrainAmount": 10}
    assert job_preset({}, profile) is profile
    assert job_preset({"base_preset": None}, profile) is profile
    chosen = job_preset({"base_preset": {"GrainAmount": 30, "Exposure2012": 2.0}}, profile)
    out = apply_style({"Exposure2012": 0.4}, chosen)
    assert out["GrainAmount"] == 30 and out["Exposure2012"] == 0.4   # exposure stays per photo


def test_only_a_look_chosen_for_the_job_brings_its_tone_sliders():
    from calotype_inference_worker.cli import styled

    predicted = {"Exposure2012": 0.4, "Contrast2012": 10}
    preset = {"Contrast2012": 80, "GrainAmount": 20}
    assert styled(predicted, preset, chosen=False)["Contrast2012"] == 10   # profile preset: look only
    assert styled(predicted, preset, chosen=True)["Contrast2012"] == 80    # chosen: like by hand
    assert styled(predicted, preset, chosen=True)["GrainAmount"] == 20


def test_measured_light_is_read_from_the_exif_snapshot():
    assert measured_light({"wb_measured_kelvin": 5574}) == 5574.0
    assert measured_light({"wb_measured_kelvin": "5574"}) is None
    assert measured_light({"wb_measured_kelvin": 0}) is None
    assert measured_light({}) is None and measured_light(None) is None


def test_calibration_runs_with_and_without_camera_light():
    ids, settings, predictions, vectors = _job([0.5, 0.7], untouched=3)
    light = {p: 5000.0 + 100 * i for i, p in enumerate(ids)}
    assert calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4(), light=light) == ids[2:]
    light[ids[4]] = None      # one photo without a measurement: the light is left out for all
    ids, settings, predictions, vectors = _job([0.5, 0.7], untouched=3)
    assert calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4(), light=dict(zip(ids, [5000.0] * 4 + [None]))) == ids[2:]


def test_camera_exposure_is_read_from_the_exif_snapshot():
    assert camera_exposure({"iso": 400, "shutter_speed": 0.004, "aperture": 2.8, "exposure_bias": 0.33}) == pytest.approx(
        [8.6439, -7.9658, 1.4854, 0.33], abs=1e-3)
    assert camera_exposure({"iso": 400, "shutter_speed": 0.004, "aperture": 2.8})[3] == 0.0
    assert camera_exposure({"iso": 400, "shutter_speed": 0.004}) is None
    assert camera_exposure({"iso": 0, "shutter_speed": 0.004, "aperture": 2.8}) is None
    assert camera_exposure({"iso": "400", "shutter_speed": 0.004, "aperture": 2.8}) is None
    assert camera_exposure(None) is None


def test_calibration_runs_with_camera_exposure():
    ids, settings, predictions, vectors = _job([0.5, 0.7], untouched=3)
    camera = {p: [8.0 + i, -7.0, 1.5, 0.0] for i, p in enumerate(ids)}
    assert calibrate_to_shoot(predictions, vectors, settings, ids, "raw", uuid4(), camera=camera) == ids[2:]
