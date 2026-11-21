from calotype_edit_serializer import apply_style, style_settings

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


def test_glow_is_part_of_the_look():
    from calotype_edit_serializer import style_settings

    look = style_settings({"Glow": 60, "GlowStyle": 4, "GlowWarmth": 20, "Exposure2012": 1.0})
    assert look == {"Glow": 60, "GlowStyle": 4, "GlowWarmth": 20}


def test_shared_style_takes_what_most_edited_photos_share():
    from calotype_edit_serializer import shared_style

    curve = [0, 0, 128, 140, 255, 255]
    edits = [{"Glow": 40, "ToneCurvePV2012": curve, "Vibrance": 10, "Exposure2012": 0.3, "GrainAmount": 0}
             for _ in range(3)]
    edits.append({"Glow": 0, "ToneCurvePV2012": [0, 0, 255, 255], "Vibrance": 30, "GrainAmount": 25})
    out = shared_style(edits)
    assert out == {"Glow": 40, "ToneCurvePV2012": curve, "GrainAmount": 0}  # no vibrance, no exposure


def test_shared_style_spreads_no_look_used_on_few_photos():
    from calotype_edit_serializer import shared_style

    edits = [{"Glow": 60}, {}, {}, {"Glow": 20}, {"Glow": 20}, {}]
    assert shared_style(edits) == {}               # 3 of 6 have no glow: no majority value
    assert shared_style([{"Glow": 60}, {"Glow": 20}]) == {}   # tie
    assert shared_style([]) == {}


def test_a_chosen_preset_brings_its_tone_sliders_and_keeps_exposure_and_white_balance():
    from calotype_edit_serializer import apply_preset

    predicted = {"Exposure2012": 0.4, "Temperature": 5000, "Tint": 8, "Contrast2012": 10, "Highlights2012": -20}
    preset = {"Exposure2012": 1.5, "Contrast2012": 96, "Highlights2012": -69, "Whites2012": -58,
              "WhiteBalance": "Custom", "Temperature": 7259, "Tint": 3, "Saturation": -32,
              "SplitToningHighlightHue": 45, "MaskGroupBasedCorrections": [{"x": 1}]}
    out = apply_preset(predicted, preset)
    assert (out["Contrast2012"], out["Highlights2012"], out["Whites2012"]) == (96, -69, -58)
    assert out["Saturation"] == -32 and out["SplitToningHighlightHue"] == 45
    assert out["Exposure2012"] == 0.4 and out["Tint"] == 8          # per photo
    assert "MaskGroupBasedCorrections" not in out
    # 44 mired warmer than daylight → the predicted 5000 K becomes about 6400 K
    assert 6350 <= out["Temperature"] <= 6450
    # As Shot preset or none: white balance untouched
    assert apply_preset(predicted, {"WhiteBalance": "As Shot", "Contrast2012": 5})["Temperature"] == 5000
    assert apply_preset(predicted, None) == predicted
