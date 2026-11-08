"""Preview analysis stored with the photo: straighten estimate + preview size."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from lr_frameflow_feature_worker.cli import analyze_preview


def _jpeg(tilt: float) -> bytes:
    img = Image.new("L", (1200, 800), 220)
    d = ImageDraw.Draw(img)
    for x in range(200, 1050, 100):
        d.rectangle([x, 100, x + 15, 700], fill=40)
    buf = io.BytesIO()
    img.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=220).convert("RGB").save(buf, "JPEG")
    return buf.getvalue()


def test_tilted_preview_is_measured():
    a = analyze_preview(_jpeg(2.0))
    assert a["preview_size"] == [1200, 800]
    assert a["straighten"]["lines"] >= 5 and abs(a["straighten"]["crop_angle"] + 2.0) < 0.2


def test_undecodable_preview_gives_no_analysis():
    assert analyze_preview(b"not a jpeg") == {}
