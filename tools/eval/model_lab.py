"""Offline model lab: which features and models predict a set of real edits best?

    python tools/eval/model_lab.py <preview_dir> <raw_dir> <work_dir> [--faces features.json]

Uses the train/test split from `holdout.py split` and the same previews the Bridge sends.
Compares feature sets (the production 128-bin histogram, + tone/color statistics,
+ face brightness from the culling analysis) and models (Ridge as in production,
gradient boosting) per slider — before anything goes into the pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from common import SLIDERS, read_xmp  # noqa: E402

from calotype_inference_pipeline import extract_features  # noqa: E402

TARGETS = ["Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012"]


STATS_EDGE = 400  # statistics barely change below full size, but run ~10x faster


def small(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = rgb.shape[:2]
    scale = min(1.0, STATS_EDGE / max(h, w))
    if scale == 1.0:
        return rgb, 1.0
    im = Image.fromarray(rgb).resize((round(w * scale), round(h * scale)), Image.BILINEAR)
    return np.asarray(im), scale


def tone_color_stats(rgb: np.ndarray) -> list[float]:
    f = rgb.astype(np.float32) / 255.0
    luma = 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    pct = np.percentile(luma, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    return [*pct, luma.mean(), luma.std(), *f.reshape(-1, 3).mean(axis=0),
            float(f[..., 2].mean() - f[..., 0].mean()), float(f[..., 1].mean() - (f[..., 0] + f[..., 2]).mean() / 2),
            sat.mean(), np.percentile(sat, 90), (luma > 0.98).mean(), (luma < 0.02).mean()]


def face_stats(rgb: np.ndarray, faces: list[dict], scale: float = 1.0) -> list[float]:
    """Brightness and color of the largest face; NaN-free fallback (no face) = whole image."""
    f = rgb.astype(np.float32) / 255.0
    if faces:
        x, y, w, h = (round(v * scale) for v in max(faces, key=lambda d: d["rel_size"])["box"])
        crop = f[max(0, y): y + h, max(0, x): x + w]
        if crop.size:
            luma = 0.299 * crop[..., 0] + 0.587 * crop[..., 1] + 0.114 * crop[..., 2]
            m = crop.reshape(-1, 3).mean(axis=0)
            return [1.0, float(np.median(luma)), float(luma.mean()), float(m[2] - m[0]), float(m[1] - (m[0] + m[2]) / 2)]
    luma = 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]
    return [0.0, float(np.median(luma)), float(luma.mean()), 0.0, 0.0]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preview_dir", type=Path)
    ap.add_argument("raw_dir", type=Path)
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--faces", type=Path, help="features JSON from cull_compare --cache")
    a = ap.parse_args()

    faces_by_name = {}
    if a.faces and a.faces.exists():
        faces_by_name = {Path(d["name"]).stem: d["faces"] for d in json.loads(a.faces.read_text(encoding="utf-8"))}

    def load(list_file: str):
        names = [n for n in (a.work_dir / list_file).read_text(encoding="utf-8").split() if n]
        X = {"hist": [], "hist+stats": [], "hist+stats+face": []}
        Y = []
        for n in names:
            stem = Path(n).stem
            preview = a.preview_dir / f"{stem}.jpg"
            if not preview.exists():
                continue
            raw = preview.read_bytes()
            rgb, scale = small(np.asarray(Image.open(preview).convert("RGB")))
            hist = extract_features(raw)
            stats = tone_color_stats(rgb)
            face = face_stats(rgb, faces_by_name.get(stem, []), scale)
            X["hist"].append(hist)
            X["hist+stats"].append(hist + stats)
            X["hist+stats+face"].append(hist + stats + face)
            truth = read_xmp(a.raw_dir / f"{stem}.xmp")
            Y.append([truth.get(k, 0.0) for k in TARGETS])
        return {k: np.array(v) for k, v in X.items()}, np.array(Y)

    cache = a.work_dir / "model_lab_features.npz"
    if cache.exists():
        z = np.load(cache)
        Xtr = {k[3:]: z[k] for k in z.files if k.startswith("tr_")}
        Xte = {k[3:]: z[k] for k in z.files if k.startswith("te_")}
        Ytr, Yte = z["Ytr"], z["Yte"]
        print(f"loaded cached features from {cache}")
    else:
        Xtr, Ytr = load("train.txt")
        Xte, Yte = load("test.txt")
        np.savez(cache, Ytr=Ytr, Yte=Yte, **{f"tr_{k}": v for k, v in Xtr.items()},
                 **{f"te_{k}": v for k, v in Xte.items()})
    print(f"train {len(Ytr)}, test {len(Yte)}, faces known for {len(faces_by_name)} photos\n")

    models = {
        "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "boosting": lambda: HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05,
                                                          l2_regularization=1.0, random_state=0),
    }
    header = f"{'features':<18}{'model':<10}" + "".join(f"{k.replace('2012', ''):>14}" for k in TARGETS[:3]) + "   all-3 ok"
    print("MAE (share within tolerance)\n" + header)
    guess = np.abs(Ytr.mean(axis=0) - Yte).mean(axis=0)
    print(f"{'—':<18}{'guess':<10}" + "".join(f"{guess[j]:>9.2f}      " for j in range(3)))
    results = {}
    for fname in Xtr:
        if fname.endswith("face") and not faces_by_name:
            continue
        for mname, make in models.items():
            pred = np.column_stack([make().fit(Xtr[fname], Ytr[:, j]).predict(Xte[fname])
                                    for j in range(len(TARGETS))])
            err = np.abs(pred - Yte)
            tol = np.array([SLIDERS[k][0] for k in TARGETS])
            ok = err <= tol
            cells = "".join(f"{err[:, j].mean():>8.2f} ({ok[:, j].mean():>3.0%})" for j in range(3))
            all3 = ok[:, :3].all(axis=1).mean()
            print(f"{fname:<18}{mname:<10}{cells}   {all3:>6.0%}")
            results[f"{fname}/{mname}"] = {k: float(err[:, j].mean()) for j, k in enumerate(TARGETS)} | {"all3_within": float(all3)}
    (a.work_dir / "model_lab.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
