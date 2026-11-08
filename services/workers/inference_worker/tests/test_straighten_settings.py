"""Edit jobs with straighten: crop keys only for photos with a clear reference."""

from __future__ import annotations

from lr_frameflow_inference_worker.cli import straighten_settings


def test_clear_reference_gives_lightroom_crop_keys():
    s = straighten_settings({"preview_size": [800, 1200],
                             "straighten": {"crop_angle": 3.0, "lines": 8, "spread": 0.2}})
    assert s["CropAngle"] == 3.0 and s["HasCrop"] is True
    # Sensor frame is landscape even for an upright portrait preview (6000×4000 → 0.0526).
    assert round(s["CropLeft"], 4) == 0.0526 and s["CropTop"] == 0.0


def test_no_reference_or_no_analysis_leaves_the_crop_alone():
    assert straighten_settings({"preview_size": [1200, 800],
                                "straighten": {"crop_angle": 0.0, "lines": 0, "spread": 0.0}}) == {}
    assert straighten_settings({"preview_size": [1200, 800],
                                "straighten": {"crop_angle": 1.2, "lines": 2, "spread": 0.1}}) == {}
    assert straighten_settings({}) == {} and straighten_settings(None) == {}
