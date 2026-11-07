from lr_edit_serializer import apply_style, style_settings

PRESET = {
    # look
    "ToneCurvePV2012": [0, 18, 64, 60, 192, 200, 255, 245],
    "HueAdjustmentGreen": -20,
    "ColorGradeShadowHue": 200,
    "ColorGradeShadowSat": 12,
    "Clarity2012": 10,
    "Saturation": -16,
    "GrainAmount": 25,
    "CameraProfile": "Adobe Standard",
    # made on another photo: must not leak
    "Exposure2012": 1.2,
    "Temperature": 7400,
    "WhiteBalance": "Custom",
    "CropTop": 0.1,
    "MaskGroupBasedCorrections": [{"x": 1}],
    "LensProfileName": "Some lens",
}


def test_style_keeps_only_the_look():
    s = style_settings(PRESET)
    assert s["ToneCurvePV2012"] == [0.0, 18.0, 64.0, 60.0, 192.0, 200.0, 255.0, 245.0]
    assert s["HueAdjustmentGreen"] == -20 and s["ColorGradeShadowSat"] == 12
    assert s["Saturation"] == -16 and s["CameraProfile"] == "Adobe Standard"
    for leaked in ("Exposure2012", "Temperature", "WhiteBalance", "CropTop",
                   "MaskGroupBasedCorrections", "LensProfileName"):
        assert leaked not in s, leaked


def test_prediction_wins_for_photo_dependent_sliders():
    predicted = {"Exposure2012": 0.35, "Temperature": 5600.0, "Saturation": 0.0}
    merged = apply_style(predicted, PRESET)
    assert merged["Exposure2012"] == 0.35
    assert merged["Temperature"] == 5600.0
    assert merged["Saturation"] == -16, "look slider comes from the preset"
    assert merged["Clarity2012"] == 10


def test_no_preset_changes_nothing():
    predicted = {"Exposure2012": 0.35}
    assert apply_style(predicted, None) == predicted
    assert apply_style(predicted, {}) == predicted


def test_broken_curve_is_dropped():
    assert "ToneCurvePV2012" not in style_settings({"ToneCurvePV2012": [0, 0, 255]})
    assert "ToneCurvePV2012" not in style_settings({"ToneCurvePV2012": ["a", "b"]})
