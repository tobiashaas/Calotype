"""Few-shot shoot calibration on a prepared pool: k edited examples spread over one shoot,
the other photos are predicted from them (no profile), scored per slider and all together.

    python tools/eval/shoot_lab.py pool.npz [--k 10 20 50]

pool.npz holds one shoot: X (photos x features, current feature version), Y (photos x sliders,
internal names in `--sliders` order), names (sorted = capture order) and optionally light (the
camera's measured colour temperature per photo, Kelvin) and camera (per photo log2 ISO, log2
shutter seconds, log2 f-number, exposure compensation) and times (capture time in seconds —
the plugin always sends it, so a pool without times understates shoots edited scene by scene). Pools made from another
tool's edits are an internal yardstick only — never commit them or anything fitted on them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "libs" / "inference-pipeline" / "src"))
from calotype_inference_pipeline.shoot import TOLERANCE, calibrate  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def score(X: np.ndarray, Y: np.ndarray, sliders: list[str], k: int, offsets: int = 4,
          light: np.ndarray | None = None, camera: np.ndarray | None = None,
          times: np.ndarray | None = None) -> np.ndarray:
    """Share of the predicted photos within tolerance: per slider, then all sliders at once."""
    n = len(X)
    step = n / k
    tolerance = np.array([TOLERANCE[s] for s in sliders])
    rows = []
    for off in range(offsets):
        ref = np.unique(np.clip((np.arange(k) * step + off * step / offsets).astype(int), 0, n - 1))
        rest = np.setdiff1d(np.arange(n), ref)
        references = [dict(zip(sliders, map(float, Y[i]))) for i in ref]
        predicted, _ = calibrate(references, None, X[ref], None, X[rest],
                                 None if times is None else times[ref], None if times is None else times[rest],
                                 None if light is None else light[ref], None if light is None else light[rest],
                                 None if camera is None else camera[ref], None if camera is None else camera[rest])
        P = np.array([[row[s] for s in sliders] for row in predicted])
        ok = np.abs(P - Y[rest]) <= tolerance
        rows.append(np.append(ok.mean(axis=0), ok.all(axis=1).mean()))
    return np.mean(rows, axis=0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pools", nargs="+", type=Path)
    parser.add_argument("--k", nargs="+", type=int, default=[10, 20, 50])
    parser.add_argument("--sliders", nargs="+",
                        default=["exposure", "temp", "tint", "contrast", "highlights", "shadows"])
    parser.add_argument("--no-light", action="store_true",
                        help="ignore the pool's camera-measured colour temperature (key 'light')")
    parser.add_argument("--no-camera", action="store_true",
                        help="ignore the pool's camera exposure settings (key 'camera')")
    parser.add_argument("--no-times", action="store_true",
                        help="ignore the pool's capture times (key 'times')")
    args = parser.parse_args()
    print(f"{'pool':<22}{'k':>4}  " + " ".join(f"{s[:8]:>8}" for s in args.sliders) + "      all")
    for path in args.pools:
        data = np.load(path, allow_pickle=True)
        order = np.argsort(data["names"])
        X, Y = data["X"][order], data["Y"][order]
        for k in args.k:
            light = data["light"][order] if "light" in data.files and not args.no_light else None
            camera = data["camera"][order] if "camera" in data.files and not args.no_camera else None
            times = data["times"][order] if "times" in data.files and not args.no_times else None
            result = score(X, Y, args.sliders, k, light=light, camera=camera, times=times)
            print(f"{path.stem:<22}{k:>4}  " + " ".join(f"{100 * v:7.1f}%" for v in result))


if __name__ == "__main__":
    main()
