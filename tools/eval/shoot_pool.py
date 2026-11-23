"""Build a pool for `shoot_lab.py` from one shoot collected by the Bridge example `pool`
(previews + photos.jsonl with the catalog's edits, read-only):

    cargo run --release -p calotype-bridge-core --example pool -- <dir> <catalog.lrcat> <raw-dir>
    python tools/eval/shoot_pool.py <dir> [--exiftool]

Writes <dir>/pool.npz: X (features of the unedited preview), Y (the photographer's sliders,
internal names), names, light (camera-measured Kelvin), times (capture time in seconds) and,
with --exiftool, camera (log2 ISO,
log2 shutter seconds, log2 f-number, exposure compensation). Only edited photos are kept.
Pools hold a photographer's work: keep them local, never commit them.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for src in ("libs/inference-pipeline/src", "libs/edit-serializer/src", "services/workers/inference_worker/src"):
    sys.path.insert(0, str(ROOT / src))
from calotype_edit_serializer import from_lightroom  # noqa: E402
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION, compute_features  # noqa: E402
from calotype_inference_worker.plan import ExifSnapshot  # noqa: E402

SLIDERS = ["exposure", "temp", "tint", "contrast", "highlights", "shadows", "whites", "blacks",
           "vibrance", "saturation"]


def camera_settings(files: list[str]) -> dict[str, dict]:
    """ISO, shutter, aperture and exposure compensation per file, read with ExifTool, as the
    keys of an EXIF snapshot (exif-snapshot-v1)."""
    # The file names go through stdin: a whole shoot does not fit on a command line.
    out = subprocess.run(
        ["exiftool", "-j", "-n", "-ISO", "-ExposureTime", "-FNumber", "-ExposureCompensation",
         "-charset", "filename=utf8", "-@", "-"],
        input=chr(10).join(files), capture_output=True, text=True, encoding="utf-8", check=False).stdout
    rows = {}
    for row in json.loads(out or "[]"):
        rows[Path(row["SourceFile"]).stem] = {
            "iso": row.get("ISO"), "shutter_speed": row.get("ExposureTime"),
            "aperture": row.get("FNumber"), "exposure_bias": row.get("ExposureCompensation")}
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", type=Path)
    parser.add_argument("--exiftool", action="store_true", help="add the camera's exposure settings")
    args = parser.parse_args()
    photos = [json.loads(line) for line in (args.dir / "photos.jsonl").read_text(encoding="utf-8").splitlines()]
    photos = [p for p in photos if p["edited"]]
    camera = camera_settings([p["file"] for p in photos]) if args.exiftool else {}
    X, Y, names, light, cam, times = [], [], [], [], [], []
    for p in photos:
        values = from_lightroom(p["settings"], "raw")
        # The same parser as the edit job: capture time, measured light, camera exposure.
        exif = ExifSnapshot.from_snapshot({**p, **camera.get(p["name"], {})})
        if any(s not in values for s in SLIDERS) or (args.exiftool and exif.camera_exposure is None):
            continue
        X.append(compute_features((args.dir / "previews" / f"{p['name']}.jpg").read_bytes(), CURRENT_FEATURE_VERSION))
        Y.append([float(values[s]) for s in SLIDERS])
        names.append(p["name"])
        light.append(exif.measured_kelvin or np.nan)
        cam.append(exif.camera_exposure or [np.nan] * 4)
        times.append(np.nan if exif.capture_time is None else exif.capture_time)
    extra = {"camera": np.array(cam)} if args.exiftool else {}
    if not np.isnan(light).any():
        extra["light"] = np.array(light)
    if not np.isnan(times).any():
        extra["times"] = np.array(times)
    np.savez(args.dir / "pool.npz", X=np.array(X), Y=np.array(Y), names=np.array(names), **extra)
    Yn = np.array(Y)
    print(f"{args.dir.name}: {len(names)} edited photos, extras: {sorted(extra)}")
    print("  spread (std) " + "  ".join(f"{s[:5]} {Yn[:, i].std():.2f}" for i, s in enumerate(SLIDERS)))


if __name__ == "__main__":
    main()
