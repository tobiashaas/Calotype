"""Straighten: rotate only on clear reference lines, in Lightroom's CropAngle convention."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from lr_frameflow_inference_pipeline.straighten import crop_settings, estimate_tilt, tilt_from_segments


def _building(tilt: float) -> Image.Image:
    """Dark vertical bars (like door frames) on a light wall, then tilted by `tilt` degrees."""
    img = Image.new("L", (1400, 1000), 220)
    d = ImageDraw.Draw(img)
    for x in range(250, 1200, 120):
        d.rectangle([x, 120, x + 18, 880], fill=40)
    return img.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=220).convert("RGB")


def test_level_building_needs_no_rotation():
    t = estimate_tilt(_building(0.0))
    assert t.confident and abs(t.crop_angle) < 0.15


def test_tilted_building_is_levelled_in_lightroom_convention():
    # PIL rotates counter-clockwise; Lightroom's CropAngle for that photo is negative of it.
    for tilt in (1.5, -2.0):
        t = estimate_tilt(_building(tilt))
        assert t.confident
        assert abs(t.crop_angle + tilt) < 0.2, (tilt, t)


def test_no_reference_lines_means_no_rotation():
    rng = np.random.default_rng(1)
    noise = Image.fromarray(rng.integers(0, 255, (800, 1200), dtype=np.uint8))
    t = estimate_tilt(noise)
    assert (t.crop_angle, t.confident) == (0.0, False)


def test_a_few_short_or_odd_lines_do_not_rotate():
    # Two long tilted lines (a hat brim, an arm) are not enough evidence.
    seg = np.array([[100, 100, 900, 130], [100, 400, 900, 430]], dtype=float)
    assert tilt_from_segments(seg, 1000, 800).crop_angle == 0.0


def test_crop_matches_lightroom():
    # Read from Lightroom Classic 15.6 (Develop, straighten 3° on a 6000×4000 CR3).
    c = crop_settings(3.0, 6000, 4000)
    assert (round(c["CropLeft"], 4), round(c["CropTop"], 4)) == (0.0526, 0.0)
    assert (round(c["CropRight"], 4), round(c["CropBottom"], 4)) == (0.9474, 1.0)
    assert c["HasCrop"] is True


def test_negative_angle_corners_and_zero_is_full_frame():
    # Corners of the rotated rectangle, not a mirrored box: -3.16° as Lightroom stores it
    # (value from a real straightened sidecar).
    c = crop_settings(-3.16, 6000, 4000)
    assert [round(c[k], 3) for k in ("CropLeft", "CropTop", "CropRight", "CropBottom")] == [0.021, 0.076, 0.979, 0.924]
    assert crop_settings(0.0, 6000, 4000)["CropRight"] == 1.0
