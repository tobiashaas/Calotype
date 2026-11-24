from calotype_edit_serializer import edited_photos, unchanged_since

UNTOUCHED = {"WhiteBalance": "As Shot", "Temperature": 5100, "Tint": 3, "Exposure2012": 0}


def test_defaults_are_untouched_even_with_different_as_shot_kelvin():
    photos = [UNTOUCHED, {**UNTOUCHED, "Temperature": 6400}, {**UNTOUCHED, "Exposure2012": 0.4}]
    assert edited_photos(photos, "raw") == [False, False, True]


def test_custom_white_balance_is_an_edit():
    photos = [UNTOUCHED, UNTOUCHED, {**UNTOUCHED, "WhiteBalance": "Custom", "Temperature": 5600}]
    assert edited_photos(photos, "raw") == [False, False, True]


def test_synced_edits_outnumbering_untouched_photos_are_still_edits():
    synced = {**UNTOUCHED, "Exposure2012": 0.7, "Contrast2012": 20}
    assert edited_photos([UNTOUCHED, synced, synced, synced], "raw") == [False, True, True, True]


def test_import_preset_is_the_most_common_state():
    preset = {**UNTOUCHED, "Contrast2012": 15, "Vibrance": 10}
    photos = [preset, preset, preset, {**preset, "Exposure2012": -0.3}]
    assert edited_photos(photos, "raw") == [False, False, False, True]


def test_no_shared_state_means_no_examples():
    photos = [{"Exposure2012": 0.1, "Contrast2012": 5}, {"Exposure2012": 0.2, "Contrast2012": 5}]
    assert edited_photos(photos, "raw") == [False, False]


def test_jpeg_uses_relative_white_balance():
    photos = [{}, {"IncrementalTemperature": 0}, {"IncrementalTemperature": 12}]
    assert edited_photos(photos, "jpeg_tiff") == [False, False, True]


def test_keeps_as_shot_only_for_raw_on_camera_white_balance():
    from calotype_edit_serializer import keeps_as_shot

    assert keeps_as_shot({"WhiteBalance": "As Shot", "Temperature": 5100}, "raw")
    assert keeps_as_shot({}, "raw")
    assert not keeps_as_shot({"Temperature": 4519}, "raw")   # explicit Kelvin: its own
    assert not keeps_as_shot({"WhiteBalance": "Custom", "Temperature": 5100}, "raw")
    assert not keeps_as_shot({"WhiteBalance": "As Shot"}, "jpeg_tiff")


APPLIED = {"Exposure2012": 0.35, "Temperature": 5600, "Tint": 4, "Contrast2012": -36, "ToneCurvePV2012": [0, 0, 255, 255]}


def test_a_photo_left_as_calotype_set_it_is_unchanged_at_lightrooms_precision():
    current = {**APPLIED, "Exposure2012": 0.354, "Highlights2012": -60, "ToneCurvePV2012": [0, 10, 255, 255]}
    # Highlights and the curve were not set by the result: whatever the photo holds there counts as unchanged.
    assert unchanged_since(APPLIED, current, "raw") is True


def test_a_moved_slider_is_a_correction():
    assert unchanged_since(APPLIED, {**APPLIED, "Exposure2012": 0.5}, "raw") is False
    assert unchanged_since(APPLIED, {**APPLIED, "Temperature": 5650}, "raw") is False
    assert unchanged_since(APPLIED, {k: v for k, v in APPLIED.items() if k != "Temperature"}, "raw") is False


def test_a_result_without_sliders_proves_nothing():
    assert unchanged_since({"CropAngle": 1.2}, {"CropAngle": 1.2}, "raw") is False
    assert unchanged_since({}, {}, "raw") is False


def test_a_slider_lightroom_omits_counts_as_its_default():
    assert unchanged_since({"Contrast2012": 0}, {}, "jpeg_tiff") is True
