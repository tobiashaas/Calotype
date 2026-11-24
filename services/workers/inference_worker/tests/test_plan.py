"""The edit plan: what each photo of an edit job gets (plan_edit, ShootPhoto, ExifSnapshot)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from calotype_domain.failures import failure_code

from calotype_inference_worker.plan import (
    EditProfile,
    EditRequest,
    ExifSnapshot,
    NoExamplesError,
    ShootPhoto,
    plan_edit,
)

UNTOUCHED = {"WhiteBalance": "As Shot", "Temperature": 5000, "Tint": 0, "Exposure2012": 0}
PREDICTED = {"exposure": -1.0, "contrast": 0.0, "temp": 5000.0, "tint": 0.0}
LEVEL = {"preview_size": [800, 1200], "straighten": {"crop_angle": 3.0, "lines": 8, "spread": 0.2}}


def _profile(predicted=None, **kwargs) -> EditProfile:
    values = PREDICTED if predicted is None else predicted
    return EditProfile("raw", lambda vector, as_shot, *_: dict(values), **kwargs)


def _shoot(edited_exposures, untouched, times=None, **extra):
    """Edited photos first (exposure as given, contrast 10, plus ``extra`` settings), then
    untouched ones."""
    photos = []
    for i, e in enumerate(list(edited_exposures) + [None] * untouched):
        settings = dict(UNTOUCHED) if e is None else {**UNTOUCHED, "Exposure2012": e, "Contrast2012": 10, **extra}
        exif = ExifSnapshot(capture_time=None if times is None else times[i])
        photos.append(ShootPhoto(uuid4(), settings, [float(i), 1.0], exif))
    return photos


def _by_id(plan):
    return {r.photo_id: r for r in plan.results}


LEARN = EditRequest(learn_from_edits=True)


# --- examples and targets -------------------------------------------------------------------

def test_edited_photos_set_the_look_and_get_no_result():
    photos = _shoot([0.5, 0.7], untouched=3)
    plan = plan_edit(LEARN, _profile(), photos)
    assert [r.photo_id for r in plan.results] == [p.photo_id for p in photos[2:]]
    for r in plan.results:
        assert r.lr_settings["Exposure2012"] == 0.6
        assert r.lr_settings["Contrast2012"] == 10


def test_without_edited_photos_every_prediction_stays():
    photos = _shoot([], untouched=4)
    plan = plan_edit(LEARN, _profile(), photos)
    assert len(plan.results) == 4
    assert all(r.lr_settings["Exposure2012"] == -1.0 for r in plan.results)


def test_without_learning_from_edits_every_photo_gets_the_profiles_prediction():
    photos = _shoot([0.5, 0.7], untouched=2)
    plan = plan_edit(EditRequest(), _profile(), photos)
    assert len(plan.results) == 4
    assert all(r.lr_settings["Exposure2012"] == -1.0 for r in plan.results)


def test_photos_without_features_are_neither_examples_nor_targets():
    photos = _shoot([0.5, 0.7], untouched=2)
    photos[0] = ShootPhoto(photos[0].photo_id, photos[0].settings, None)
    photos[3] = ShootPhoto(photos[3].photo_id, photos[3].settings, None)
    plan = plan_edit(LEARN, _profile(), photos)
    assert [r.photo_id for r in plan.results] == [photos[2].photo_id]
    assert plan.results[0].lr_settings["Exposure2012"] == 0.7


def test_series_follows_the_closest_edited_photo_in_time():
    # Two scenes: examples 0-4 in the morning (exposure 0.2), 5-9 in the evening (1.2).
    times = [i % 5 for i in range(5)] + [36000 + i for i in range(5, 10)] + [2.5, 36007.5]
    photos = _shoot([0.2] * 5 + [1.2] * 5, untouched=2, times=times)
    results = plan_edit(LEARN, _profile(), photos).results
    assert [r.photo_id for r in results] == [p.photo_id for p in photos[10:]]
    # Exposure of the closest example fades with the seconds between, so nearly its value.
    assert results[0].lr_settings["Exposure2012"] == pytest.approx(0.2, abs=0.05)
    assert results[1].lr_settings["Exposure2012"] == pytest.approx(1.2, abs=0.05)


def test_without_a_profile_only_the_edited_sliders_are_set():
    photos = _shoot([0.5, 0.7], untouched=3)
    plan = plan_edit(LEARN, EditProfile("raw"), photos)
    assert len(plan.results) == 3
    for r in plan.results:
        assert r.lr_settings["Exposure2012"] == 0.6 and r.lr_settings["Contrast2012"] == 10
        assert "Temperature" not in r.lr_settings   # RAW as shot: no Kelvin to copy, none invented
    with pytest.raises(NoExamplesError, match="no edited photos") as failed:
        plan_edit(LEARN, EditProfile("raw"), _shoot([], untouched=3))
    assert failure_code(failed.value) == "no_examples"   # the job's failure code


def test_a_photo_on_the_cameras_white_balance_passes_its_as_shot_kelvin():
    seen = []
    profile = EditProfile("raw", lambda vector, as_shot, *_: seen.append(as_shot) or dict(PREDICTED))
    custom = {**UNTOUCHED, "WhiteBalance": "Custom", "Temperature": 6100}
    photos = [ShootPhoto(uuid4(), dict(UNTOUCHED), [0.0]), ShootPhoto(uuid4(), custom, [1.0])]
    plan_edit(EditRequest(), profile, photos)
    assert seen == [5000.0, None]


def test_calibration_uses_camera_light_and_exposure_only_when_every_photo_has_them():
    photos = _shoot([0.5, 0.7], untouched=3)
    lit = [ShootPhoto(p.photo_id, p.settings, p.vector,
                      ExifSnapshot(measured_kelvin=5000.0 + 100 * i, iso=400, shutter_speed=0.01 * (i + 1),
                                   aperture=2.8))
           for i, p in enumerate(photos)]
    notes = " ".join(plan_edit(LEARN, _profile(), lit).notes)
    assert "camera light True" in notes and "camera exposure True" in notes
    lit[4] = ShootPhoto(lit[4].photo_id, lit[4].settings, lit[4].vector)   # one without measurements
    plan = plan_edit(LEARN, _profile(), lit)
    assert "camera light False" in " ".join(plan.notes) and len(plan.results) == 3


# --- series consistency ---------------------------------------------------------------------

def _burst(exposures, times):
    vectors = iter([[0.5 + 0.001 * i, 0.2, 0.9] for i in range(len(exposures))])
    by_vector = {}
    photos = []
    for e, t in zip(exposures, times):
        v = next(vectors)
        by_vector[tuple(v)] = {"exposure": e, "temp": 5200.0, "tint": 0.0}
        photos.append(ShootPhoto(uuid4(), dict(UNTOUCHED), v, ExifSnapshot(capture_time=t)))
    return photos, EditProfile("raw", lambda vector, as_shot, *_: dict(by_vector[tuple(vector)]))


def test_a_burst_is_pulled_together():
    photos, profile = _burst([0.0, 0.2, 0.6, 0.4], [0.0, 1.0, 2.0, 3.0])
    plan = plan_edit(EditRequest(consistent_series=True), profile, photos)
    exposures = [r.lr_settings["Exposure2012"] for r in plan.results]
    assert max(exposures) - min(exposures) < 0.6


def test_without_capture_times_nothing_is_smoothed():
    photos, profile = _burst([0.0, 0.2, 0.6, 0.4], [0.0, None, 2.0, 3.0])
    plan = plan_edit(EditRequest(consistent_series=True), profile, photos)
    assert [r.lr_settings["Exposure2012"] for r in plan.results] == [0.0, 0.2, 0.6, 0.4]
    assert any("no series consistency" in n for n in plan.notes)


# --- precedence: prediction → preset → shoot look → crop; mask strengths -------------------

OWN_CROP = {"CropAngle": 1.5, "CropRight": 0.9}

PRECEDENCE = [
    # (case, request, profile preset, example look, own settings, expected keys, kept_crop)
    ("profile preset adds only its look", EditRequest(), {"Contrast2012": 80, "GrainAmount": 20}, None, {},
     {"Contrast2012": 10, "GrainAmount": 20}, False),
    ("chosen look replaces the profile's, with its tone sliders",
     EditRequest(look={"Contrast2012": 80, "GrainAmount": 30, "Exposure2012": 2.0}), {"GrainAmount": 20}, None, {},
     {"Contrast2012": 80, "GrainAmount": 30, "Exposure2012": 0.4}, False),
    ("the shoot's look wins over a chosen look",
     EditRequest(learn_from_edits=True, look={"GrainAmount": 30}), {}, {"GrainAmount": 45}, {},
     {"GrainAmount": 45}, False),
    ("straighten adds crop keys", EditRequest(straighten=True), {}, None, {},
     {"CropAngle": 3.0, "HasCrop": True}, False),
    ("a photo with its own crop keeps it", EditRequest(straighten=True), {}, None, OWN_CROP,
     {"CropAngle": None, "HasCrop": None}, True),
    ("a numeric-string own crop counts too", EditRequest(straighten=True), {}, None, {"CropAngle": "1.2"},
     {"CropAngle": None}, True),
    ("no straighten, no crop keys", EditRequest(), {}, None, {}, {"CropAngle": None}, False),
]


@pytest.mark.parametrize("case,request_,preset,example_look,own,expected,kept", PRECEDENCE,
                         ids=[c[0] for c in PRECEDENCE])
def test_precedence(case, request_, preset, example_look, own, expected, kept):
    profile = _profile({"exposure": 0.4, "contrast": 10.0}, base_preset=preset)
    target = ShootPhoto(uuid4(), {**UNTOUCHED, **own}, [9.0, 1.0], analysis=LEVEL)
    photos = [target, ShootPhoto(uuid4(), dict(UNTOUCHED), [8.0, 1.0])]
    if example_look is not None:
        photos += [ShootPhoto(uuid4(), {**UNTOUCHED, "Exposure2012": 0.5, **example_look}, [float(i), 1.0])
                   for i in range(2)]
    result = _by_id(plan_edit(request_, profile, photos))[target.photo_id]
    for key, value in expected.items():
        assert result.lr_settings.get(key) == value, key
    assert result.kept_crop is kept
    if kept:
        assert not any(k.startswith("Crop") for k in result.lr_settings)


SUBJECT = {"What": "Mask/Image", "MaskSubType": 1, "MaskBlendMode": 0}


def _masked(shadows):
    return {"MaskGroupBasedCorrections": [
        {"CorrectionAmount": 1, "CorrectionMasks": [SUBJECT], "LocalShadows2012": shadows}]}


@pytest.mark.parametrize("learn,examples_have_masks,expected", [
    (False, True, {"sky": {"LocalHighlights2012": -0.3}}),       # the profile's
    (True, True, {"subject": {"LocalShadows2012": 0.2}}),         # the examples' replace it
    (True, False, None),                                          # examples without masks: none
])
def test_mask_strengths(learn, examples_have_masks, expected):
    photos = _shoot([0.5, 0.7, 0.6], untouched=2)
    for p, shadows in zip(photos[:3], [0.1, 0.2, 0.3]):
        if examples_have_masks:
            p.settings.update(_masked(shadows))
    photos[3].settings.update(_masked(-0.9))   # an untouched photo with a mask is no example
    profile = _profile(retouch={"sky": {"LocalHighlights2012": -0.3}})
    plan = plan_edit(EditRequest(learn_from_edits=learn), profile, photos)
    assert all(r.retouch == expected for r in plan.results)


def test_the_shoots_look_comes_from_the_edited_photos_only():
    photos = _shoot([0.5, 0.7, 0.6], untouched=2, Glow=45, GlowStyle=2, ColorGradeMidtoneHue=30)
    for r in plan_edit(LEARN, _profile(), photos).results:
        assert {k: r.lr_settings[k] for k in ("Glow", "GlowStyle", "ColorGradeMidtoneHue")} == {
            "Glow": 45, "GlowStyle": 2, "ColorGradeMidtoneHue": 30}
    for r in plan_edit(EditRequest(), _profile(), photos).results:   # no examples, no look
        assert "Glow" not in r.lr_settings


def test_request_from_payload():
    assert EditRequest.from_payload({}) == EditRequest()
    assert EditRequest.from_payload({"base_preset": None}).look is None
    assert EditRequest.from_payload({"base_preset": {}}).look is None
    r = EditRequest.from_payload({"straighten": True, "learn_from_edits": True, "consistent_series": True,
                                  "base_preset": {"GrainAmount": 30}})
    assert r == EditRequest(True, True, True, {"GrainAmount": 30})


def test_straighten_needs_clear_lines():
    profile = _profile()
    for analysis in (None, {}, {"preview_size": [1200, 800], "straighten": {"crop_angle": 1.2, "lines": 2}},
                     {"preview_size": [1200, 800], "straighten": {"crop_angle": 0.0, "lines": 9}}):
        photo = ShootPhoto(uuid4(), dict(UNTOUCHED), [0.0], analysis=analysis)
        assert "CropAngle" not in plan_edit(EditRequest(straighten=True), profile, [photo]).results[0].lr_settings
    photo = ShootPhoto(uuid4(), dict(UNTOUCHED), [0.0], analysis=LEVEL)
    s = plan_edit(EditRequest(straighten=True), profile, [photo]).results[0].lr_settings
    # Sensor frame is landscape even for an upright portrait preview (6000×4000 → 0.0526).
    assert round(s["CropLeft"], 4) == 0.0526 and s["CropTop"] == 0.0


# --- EXIF snapshot --------------------------------------------------------------------------

def test_capture_time_from_lightroom_and_folder_mode():
    a = ExifSnapshot.from_snapshot({"date_time_original": "2022-03-19T14:05:33"}).capture_time
    b = ExifSnapshot.from_snapshot({"date_time_original": "2022-03-19T14:05:43.25+01:00"}).capture_time
    assert b - a == 10
    assert ExifSnapshot.from_snapshot({}).capture_time is None
    assert ExifSnapshot.from_snapshot(None).capture_time is None
    assert ExifSnapshot.from_snapshot({"date_time_original": "garbage"}).capture_time is None


def test_measured_light():
    assert ExifSnapshot.from_snapshot({"wb_measured_kelvin": 5574}).measured_kelvin == 5574.0
    for bad in ("5574", 0, True, None):
        assert ExifSnapshot.from_snapshot({"wb_measured_kelvin": bad}).measured_kelvin is None


def test_camera_exposure():
    full = {"iso": 400, "shutter_speed": 0.004, "aperture": 2.8, "exposure_bias": 0.33}
    assert ExifSnapshot.from_snapshot(full).camera_exposure == pytest.approx(
        [8.6439, -7.9658, 1.4854, 0.33], abs=1e-3)
    assert ExifSnapshot.from_snapshot({**full, "exposure_bias": None}).camera_exposure[3] == 0.0
    assert ExifSnapshot.from_snapshot({"iso": 400, "shutter_speed": 0.004}).camera_exposure is None
    assert ExifSnapshot.from_snapshot({**full, "iso": 0}).camera_exposure is None
    assert ExifSnapshot.from_snapshot({**full, "iso": "400"}).camera_exposure is None
    assert ExifSnapshot.from_snapshot(None).camera_exposure is None


def test_the_plan_needs_no_infrastructure():
    import calotype_inference_worker.plan as plan

    source = open(plan.__file__, encoding="utf-8").read()
    for forbidden in ("redis", "sqlalchemy", "boto3", "calotype_persistence", "calotype_queue"):
        assert f"import {forbidden}" not in source and f"from {forbidden}" not in source
