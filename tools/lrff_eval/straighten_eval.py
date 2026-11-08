"""Straightening against reference angles (crs:CropAngle in XMP sidecars), plus a contact sheet.

    python tools/lrff_eval/straighten_eval.py <preview_dir> <raw_dir> [--sheet out.html] [--every N]

Reports how often we rotate at all (only on clear reference lines), how close those angles are
to the reference, and the overall error compared with never rotating. The reference is another
tool's or a photographer's straightening — a yardstick, not truth: judge the sheet by eye.
The sheet shows every photo we rotate (and the reference rotates differently): before / ours /
reference, with a grid. Local HTML, images inlined, nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from common import top_description  # noqa: E402

from lr_frameflow_inference_pipeline.straighten import estimate_tilt  # noqa: E402


def reference_angle(raw_dir: Path, stem: str) -> float | None:
    sidecar = raw_dir / f"{stem}.xmp"
    if not sidecar.exists():
        return None
    m = re.search(r'crs:CropAngle="([-+0-9.]+)"', top_description(sidecar.read_text(encoding="utf-8", errors="replace")))
    return float(m.group(1)) if m else 0.0


def _tile(img: Image.Image, crop_angle: float, label: str) -> Image.Image:
    # Lightroom's CropAngle a levels the photo the way PIL's rotate(a) does (see test_straighten).
    t = img.rotate(crop_angle, resample=Image.Resampling.BICUBIC) if crop_angle else img.copy()
    d = ImageDraw.Draw(t)
    w, h = t.size
    for i in range(1, 8):
        d.line([(w * i / 8, 0), (w * i / 8, h)], fill=(255, 40, 40), width=1)
        d.line([(0, h * i / 8), (w, h * i / 8)], fill=(255, 40, 40), width=1)
    d.rectangle([0, 0, 150, 18], fill=(0, 0, 0))
    d.text((4, 3), label, fill=(255, 255, 255))
    return t


def _data_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preview_dir", type=Path)
    ap.add_argument("raw_dir", type=Path)
    ap.add_argument("--sheet", type=Path)
    ap.add_argument("--every", type=int, default=1, help="use every N-th photo")
    a = ap.parse_args()

    previews = sorted(p for p in a.preview_dir.iterdir() if p.suffix.lower() == ".jpg")[:: a.every]
    rows, sheet = [], []
    t0 = time.perf_counter()
    for p in previews:
        ref = reference_angle(a.raw_dir, p.stem)
        if ref is None:
            continue
        img = Image.open(p)
        tilt = estimate_tilt(img)
        rows.append((ref, tilt.crop_angle, tilt.confident))
        if a.sheet and tilt.confident:
            img.thumbnail((420, 420))
            sheet.append((p.stem, ref, tilt, [_tile(img, 0, "before"),
                                              _tile(img, tilt.crop_angle, f"ours {tilt.crop_angle:+.2f}"),
                                              _tile(img, ref, f"reference {ref:+.2f}")]))
    if not rows:
        print("no photos with reference sidecars")
        return 1
    ms = 1000 * (time.perf_counter() - t0) / len(rows)
    ref, ours, conf = (np.array(c) for c in zip(*rows))
    conf = conf.astype(bool)
    err = np.abs(ours - ref)
    print(f"{len(rows)} photos, {ms:.0f} ms/photo")
    print(f"we rotate {conf.mean():.0%} of them ({conf.sum()}); reference rotates "
          f"{(np.abs(ref) > 0.01).mean():.0%}, mean |angle| {np.abs(ref).mean():.2f}°")
    if conf.any():
        e = err[conf]
        print(f"where we rotate: median |ours − ref| {np.median(e):.2f}°, within 0.3° {np.mean(e <= 0.3):.0%}, "
              f"within 0.5° {np.mean(e <= 0.5):.0%}  (never rotating there: {np.median(np.abs(ref[conf])):.2f}°)")
    print(f"all photos: mean error {err.mean():.2f}° vs. never rotating {np.abs(ref).mean():.2f}°")

    if a.sheet:
        parts = ["<!doctype html><meta charset=utf-8><title>Straighten check</title>",
                 "<style>body{font:14px system-ui;margin:16px;background:#111;color:#eee}"
                 "figure{margin:0 0 18px}img{max-width:32%;margin-right:.5%}</style>",
                 f"<h1>Straighten: {len(sheet)} photos we would rotate</h1>",
                 "<p>before · ours · reference — which one is level?</p>"]
        for stem, r, t, tiles in sorted(sheet, key=lambda s: -abs(s[2].crop_angle - s[1])):
            imgs = "".join(f'<img src="{_data_uri(x)}">' for x in tiles)
            parts.append(f"<figure><figcaption>{stem} — ours {t.crop_angle:+.2f}° ({t.lines} lines), "
                         f"reference {r:+.2f}°</figcaption>{imgs}</figure>")
        a.sheet.write_text("\n".join(parts), encoding="utf-8")
        print(f"sheet: {a.sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
