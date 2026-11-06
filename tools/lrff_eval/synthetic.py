"""Synthetic-rule test: does the pipeline learn a known editing rule?

Edits are generated from a fixed, image-dependent rule (darker image → more exposure,
bluer image → warmer white balance, flat image → more contrast, plus a constant "look").
The model trains on part of the photos and predicts the rest; we then compare against
the rule. Because the rule is known exactly, the score shows whether the whole chain
(preview → features → training → inference → XMP) works and how precise it is.

    python tools/lrff_eval/synthetic.py make  <raw_dir> <preview_dir> [--holdout 0.25]
    lrff-folder train <raw_dir> --name "Synthetic rule"
    lrff-folder apply <raw_dir> --profile "Synthetic rule"
    python tools/lrff_eval/synthetic.py score <raw_dir>

Previews come from the Bridge (`cargo run --release -p lrff-bridge-core --example preview`),
so the rule sees exactly the image the model sees. Nothing here touches the originals'
folder: run it on a copy.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TRUTH_FILE = "synthetic_truth.json"
RAW_SUFFIXES = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".orf", ".rw2"}

# Slider, tolerance for "good enough" (what a photographer would not re-touch), unit
SLIDERS = {
    "Exposure2012": (0.15, "EV"),
    "Temperature": (150.0, "K"),
    "Tint": (5.0, ""),
    "Contrast2012": (8.0, ""),
    "Highlights2012": (8.0, ""),
    "Shadows2012": (8.0, ""),
    "Whites2012": (8.0, ""),
    "Blacks2012": (8.0, ""),
    "Vibrance": (5.0, ""),
    "Saturation": (5.0, ""),
}


def rule(preview: Path) -> dict[str, float]:
    """The 'photographer' of this test: deterministic settings from image statistics."""
    rgb = np.asarray(Image.open(preview).convert("RGB"), dtype=np.float32) / 255.0
    r, g, b = rgb[..., 0].mean(), rgb[..., 1].mean(), rgb[..., 2].mean()
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    mean, std = float(luma.mean()), float(luma.std())
    bright, dark = float((luma > 0.9).mean()), float((luma < 0.1).mean())
    clamp = lambda v, lo, hi: max(lo, min(hi, v))  # noqa: E731
    return {
        "Exposure2012": round(clamp(2.5 * (0.45 - mean), -2.0, 2.0), 2),
        "Temperature": float(round(clamp(5600 + 4000 * (b - r), 3500, 8000))),
        "Tint": float(round(clamp(40 * (g - (r + b) / 2), -20, 20))),
        "Contrast2012": float(round(clamp(200 * (0.24 - std), -40, 40))),
        "Highlights2012": float(round(clamp(-300 * bright, -80, 0))),
        "Shadows2012": float(round(clamp(300 * dark, 0, 80))),
        "Whites2012": 0.0,
        "Blacks2012": -5.0,
        "Vibrance": 18.0,
        "Saturation": -6.0,
    }


def xmp(settings: dict[str, float]) -> str:
    def fmt(k: str, v: float) -> str:
        if k == "Exposure2012":
            return f"{v:+.2f}"
        if k == "Temperature":
            return f"{int(v)}"
        return f"{int(v):+d}" if v else "0"

    attrs = "\n".join(f'    crs:{k}="{fmt(k, v)}"' for k, v in settings.items())
    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="lrff-eval synthetic rule">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    crs:ProcessVersion="15.4"
    crs:WhiteBalance="Custom"
{attrs}
    crs:HasSettings="True"/>
 </rdf:RDF>
</x:xmpmeta>
"""


def read_xmp(path: Path) -> dict[str, float]:
    out = {}
    for k, v in re.findall(r'crs:(\w+)="([^"]*)"', path.read_text(encoding="utf-8")):
        try:
            out[k] = float(v.lstrip("+"))
        except ValueError:
            pass
    return out


def make(raw_dir: Path, preview_dir: Path, holdout: float, seed: int) -> None:
    raws = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in RAW_SUFFIXES)
    if not raws:
        sys.exit(f"no RAW files in {raw_dir}")
    for p in raws:
        if p.with_suffix(".xmp").exists():
            sys.exit(f"{p.with_suffix('.xmp').name} exists — run on a fresh copy")
    rng = random.Random(seed)
    test = set(rng.sample([p.name for p in raws], max(1, round(len(raws) * holdout))))
    truth = {}
    for p in raws:
        preview = preview_dir / (p.stem + ".jpg")
        if not preview.exists():
            sys.exit(f"missing preview {preview}")
        settings = rule(preview)
        split = "test" if p.name in test else "train"
        truth[p.name] = {"split": split, "settings": settings}
        if split == "train":
            p.with_suffix(".xmp").write_text(xmp(settings), encoding="utf-8")
    (raw_dir / TRUTH_FILE).write_text(json.dumps(truth, indent=1), encoding="utf-8")
    n_test = sum(1 for t in truth.values() if t["split"] == "test")
    print(f"{len(truth) - n_test} training photos got rule XMPs, {n_test} test photos left unedited")


def score(raw_dir: Path) -> int:
    truth = json.loads((raw_dir / TRUTH_FILE).read_text(encoding="utf-8"))
    train = [t["settings"] for t in truth.values() if t["split"] == "train"]
    tests = {n: t["settings"] for n, t in truth.items() if t["split"] == "test"}
    baseline = {k: float(np.mean([s[k] for s in train])) for k in SLIDERS}

    rows, missing = [], []
    for name, expected in tests.items():
        sidecar = (raw_dir / name).with_suffix(".xmp")
        if not sidecar.exists():
            missing.append(name)
            continue
        rows.append((expected, read_xmp(sidecar)))
    if not rows:
        print("no predictions found — run `lrff-folder apply` first")
        return 1

    print(f"\n{len(rows)} test photos scored ({len(missing)} without prediction), {len(train)} trained on\n")
    print(f"{'slider':<16}{'model MAE':>11}{'guess-mean MAE':>16}{'within tol.':>13}   tolerance")
    all_ok = np.ones(len(rows), dtype=bool)
    learned = 0
    for k, (tol, unit) in SLIDERS.items():
        exp = np.array([e[k] for e, _ in rows])
        got = np.array([p.get(k, np.nan) for _, p in rows])
        err = np.abs(got - exp)
        base = np.abs(baseline[k] - exp)
        ok = err <= tol
        all_ok &= ok
        constant = np.ptp([s[k] for s in train]) == 0
        if not constant and err.mean() < 0.5 * base.mean():
            learned += 1
        note = " (constant look)" if constant else ""
        print(f"{k:<16}{err.mean():>11.2f}{base.mean():>16.2f}{ok.mean():>12.0%}   ±{tol:g} {unit}{note}")
    print(f"\nphotos with every slider within tolerance: {all_ok.mean():.0%}")
    varying = sum(1 for k in SLIDERS if np.ptp([s[k] for s in train]) > 0)
    print(f"image-dependent sliders learned (error < half of guessing): {learned} of {varying}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("raw_dir", type=Path)
    m.add_argument("preview_dir", type=Path)
    m.add_argument("--holdout", type=float, default=0.25)
    m.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("score")
    s.add_argument("raw_dir", type=Path)
    a = ap.parse_args()
    if a.cmd == "make":
        make(a.raw_dir, a.preview_dir, a.holdout, a.seed)
        return 0
    return score(a.raw_dir)


if __name__ == "__main__":
    raise SystemExit(main())
