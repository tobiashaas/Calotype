import pytest

from calotype_edit_serializer import from_lightroom, serialize_for_lightroom, slider_specs, to_lightroom

INTERNAL = {
    "exposure", "temp", "tint", "contrast", "highlights",
    "shadows", "whites", "blacks", "vibrance", "saturation",
}


@pytest.mark.parametrize("fmt", ["raw", "jpeg_tiff"])
def test_specs_cover_all_model_params(fmt):
    assert {s.internal for s in slider_specs(fmt)} == INTERNAL


def test_from_lightroom_raw_maps_names():
    lr = {"Exposure2012": 0.35, "Temperature": 5600, "Tint": 12, "Contrast2012": -10}
    out = from_lightroom(lr, "raw")
    assert out["exposure"] == 0.35
    assert out["temp"] == 5600.0
    assert out["tint"] == 12.0
    assert out["contrast"] == -10.0
    assert out["shadows"] == 0.0  # omitted → neutral default


def test_from_lightroom_raw_without_temperature_omits_temp():
    out = from_lightroom({"Exposure2012": 1.0}, "raw")
    assert "temp" not in out
    assert out["tint"] == 0.0


def test_from_lightroom_jpeg_uses_incremental_white_balance():
    out = from_lightroom({"IncrementalTemperature": 15, "Temperature": 6500}, "jpeg_tiff")
    assert out["temp"] == 15.0


def test_from_lightroom_ignores_non_numeric():
    out = from_lightroom({"Exposure2012": "abc", "Vibrance": True}, "jpeg_tiff")
    assert out["exposure"] == 0.0
    assert out["vibrance"] == 0.0


def test_to_lightroom_clamps_and_rounds():
    out = to_lightroom(
        {"exposure": 7.123, "contrast": 12.6, "temp": 1200.0, "tint": -3.4, "bogus": 1},
        "raw",
    )
    assert out == {
        "Exposure2012": 5.0,
        "Contrast2012": 13.0,
        "Temperature": 2000.0,
        "Tint": -3.0,
    }


def test_to_lightroom_jpeg_keys():
    out = to_lightroom({"temp": 250.0, "exposure": 0.456}, "jpeg_tiff")
    assert out == {"IncrementalTemperature": 100.0, "Exposure2012": 0.46}


def test_roundtrip_preserves_in_range_values():
    lr = {"Exposure2012": 0.5, "Temperature": 5200.0, "Tint": 8.0, "Highlights2012": -40.0}
    back = to_lightroom(from_lightroom(lr, "raw"), "raw")
    for key, value in lr.items():
        assert back[key] == value


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        slider_specs("png")  # type: ignore[arg-type]


def test_serialize_for_lightroom_defaults_to_raw():
    assert serialize_for_lightroom({"temp": 5000}) == {"Temperature": 5000.0}
