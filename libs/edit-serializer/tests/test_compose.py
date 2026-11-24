"""Look composition: prediction → preset → shoot look → crop, own crop kept."""

from __future__ import annotations

import pytest

from calotype_edit_serializer import CROP_KEYS, compose, has_own_crop

PREDICTED = {"exposure": 0.4, "contrast": 10.0, "temp": 5600.0, "tint": 3.0}
CROP = {"CropAngle": 3.0, "CropLeft": 0.05, "CropTop": 0.0, "CropRight": 0.95, "CropBottom": 1.0, "HasCrop": True}


@pytest.mark.parametrize("kwargs,expected", [
    ({}, {"Exposure2012": 0.4, "Contrast2012": 10, "GrainAmount": None}),
    ({"preset": {"Contrast2012": 80, "GrainAmount": 20, "Exposure2012": 2.0}},
     {"Exposure2012": 0.4, "Contrast2012": 10, "GrainAmount": 20}),
    ({"preset": {"Contrast2012": 80, "GrainAmount": 20, "Exposure2012": 2.0}, "chosen_look": True},
     {"Exposure2012": 0.4, "Contrast2012": 80, "GrainAmount": 20}),
    ({"preset": {"GrainAmount": 20}, "shoot_look": {"GrainAmount": 45}}, {"GrainAmount": 45}),
    ({"preset": {"CropAngle": 5.0}}, {"CropAngle": None}),     # a preset's crop belongs to its photo
])
def test_precedence(kwargs, expected):
    settings = compose(PREDICTED, "raw", **kwargs).settings
    for key, value in expected.items():
        assert settings.get(key) == value, key


def test_crop_keys_unless_the_photo_has_its_own():
    straightened = compose(PREDICTED, "raw", crop=CROP, own_settings={"Exposure2012": 0.3})
    assert straightened.settings["CropAngle"] == 3.0 and not straightened.kept_crop
    kept = compose(PREDICTED, "raw", crop=CROP, own_settings={"CropRight": 0.97})
    assert kept.kept_crop and not any(k in kept.settings for k in CROP_KEYS)
    assert not compose(PREDICTED, "raw", crop={}, own_settings={"CropAngle": 2}).kept_crop


def test_own_crop():
    assert not has_own_crop(None) and not has_own_crop({"Exposure2012": 0.3})
    assert not has_own_crop({"CropAngle": 0, "CropLeft": 0, "CropTop": 0, "CropRight": 1, "CropBottom": 1})
    assert has_own_crop({"CropAngle": "1.2"})
    assert has_own_crop({"CropRight": 0.97})
    assert not has_own_crop({"CropAngle": "garbage", "HasCrop": True})
