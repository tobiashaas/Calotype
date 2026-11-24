"""What a training photo teaches: decided sliders only, white balance flagged as shot."""

from calotype_edit_serializer import training_target

EDITED = {"WhiteBalance": "As Shot", "Temperature": 5899, "Tint": 3, "Exposure2012": 0.7,
          "Highlights2012": -100, "Shadows2012": 45, "Contrast2012": -36}


def test_a_preset_placeholder_is_left_out_and_everything_else_stays():
    target = training_target(EDITED, "raw", {"Highlights2012": -100})
    assert "highlights" not in target.sliders
    assert target.sliders["exposure"] == 0.7 and target.sliders["shadows"] == 45


def test_a_value_the_photographer_moved_away_from_the_placeholder_is_taught():
    target = training_target({**EDITED, "Highlights2012": -46}, "raw", {"Highlights2012": -100})
    assert target.sliders["highlights"] == -46


def test_the_cameras_kelvin_is_a_target_and_flagged_as_shot():
    target = training_target(EDITED, "raw")
    assert target.as_shot is True and target.sliders["temp"] == 5899


def test_an_own_white_balance_is_not_as_shot():
    target = training_target({**EDITED, "WhiteBalance": "Custom", "Temperature": 2850, "Tint": -21}, "raw")
    assert target.as_shot is False and target.sliders["temp"] == 2850
