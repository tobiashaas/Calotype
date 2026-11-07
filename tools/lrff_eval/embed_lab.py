"""Does image content help? DINOv2 embeddings as extra features (offline experiment).

    python tools/lrff_eval/embed_lab.py <preview_dir> <work_dir>

Needs torch (CPU is fine) and the cached features from model_lab.py
(<work_dir>/model_lab_features.npz). Computes DINOv2-small embeddings (Apache-2.0, code and
weights) of the previews once (cached in <work_dir>/dinov2_vits14.npz), reduces them with
PCA, adds them to the best feature set and compares with gradient boosting.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import SLIDERS  # noqa: E402

TARGETS = ["Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012"]


def embed(preview_dir: Path, names: list[str], cache: Path) -> np.ndarray:
    if cache.exists():
        z = np.load(cache)
        if list(z["names"]) == names:
            return z["emb"]
    import torch

    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False).eval()
    mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
    out, t0 = [], time.perf_counter()
    with torch.inference_mode():
        batch = []
        for i, n in enumerate(names):
            im = Image.open(preview_dir / f"{n}.jpg").convert("RGB").resize((224, 224), Image.BICUBIC)
            x = torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0).permute(2, 0, 1)
            batch.append((x - mean) / std)
            if len(batch) == 32 or i == len(names) - 1:
                out.append(model(torch.stack(batch)).numpy())
                batch = []
            if (i + 1) % 320 == 0:
                print(f"  embedded {i + 1}/{len(names)}")
    emb = np.concatenate(out)
    print(f"embedded {len(names)} previews in {time.perf_counter() - t0:.0f} s")
    np.savez(cache, names=np.array(names), emb=emb)
    return emb


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    preview_dir, work = Path(sys.argv[1]), Path(sys.argv[2])
    z = np.load(work / "model_lab_features.npz")
    best = "hist+stats+face"
    Xtr, Xte, Ytr, Yte = z[f"tr_{best}"], z[f"te_{best}"], z["Ytr"], z["Yte"]

    def stems(f):
        return [Path(n).stem for n in (work / f).read_text(encoding="utf-8").split() if n]

    tr, te = stems("train.txt"), stems("test.txt")
    tr = [n for n in tr if (preview_dir / f"{n}.jpg").exists()]
    te = [n for n in te if (preview_dir / f"{n}.jpg").exists()]
    emb = embed(preview_dir, tr + te, work / "dinov2_vits14.npz")
    Etr, Ete = emb[: len(tr)], emb[len(tr):]

    from sklearn.decomposition import PCA
    from sklearn.ensemble import HistGradientBoostingRegressor

    tol = np.array([SLIDERS[k][0] for k in TARGETS])
    print(f"\ntrain {len(Ytr)}, test {len(Yte)}\n{'features':<28}{'Exposure':>16}{'Temperature':>18}{'Tint':>14}   all-3 ok")
    for label, k in [("v2 (hist+stats+face)", 0), ("v2 + DINOv2 PCA-16", 16), ("v2 + DINOv2 PCA-32", 32),
                     ("v2 + DINOv2 PCA-64", 64)]:
        if k:
            pca = PCA(n_components=k, random_state=0).fit(Etr)
            A, B = np.hstack([Xtr, pca.transform(Etr)]), np.hstack([Xte, pca.transform(Ete)])
        else:
            A, B = Xtr, Xte
        pred = np.column_stack([
            HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, l2_regularization=1.0,
                                          random_state=0).fit(A, Ytr[:, j]).predict(B)
            for j in range(3)
        ])
        err = np.abs(pred - Yte[:, :3])
        ok = err <= tol[:3]
        cells = "".join(f"{err[:, j].mean():>9.2f} ({ok[:, j].mean():>3.0%})" for j in range(3))
        print(f"{label:<28}{cells}   {ok.all(axis=1).mean():>6.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
