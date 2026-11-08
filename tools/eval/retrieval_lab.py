"""Retrieval experiment ("RefRetouch" / "Adaptive Color Grading" idea): take the sliders of
the most similar already-edited photos, alone or combined with the v2 model.

    python tools/eval/retrieval_lab.py <work_dir>

Needs the caches of model_lab.py (model_lab_features.npz) and embed_lab.py
(dinov2_vits14.npz) in <work_dir>.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from common import SLIDERS  # noqa: E402

TARGETS = ["Exposure2012", "Temperature", "Tint"]


def knn_predict(train_x, train_y, query_x, k, exclude_self=False):
    """Similarity-weighted mean of the k nearest training photos (cosine)."""
    a = train_x / np.linalg.norm(train_x, axis=1, keepdims=True)
    q = query_x / np.linalg.norm(query_x, axis=1, keepdims=True)
    sim = q @ a.T
    if exclude_self:
        np.fill_diagonal(sim, -np.inf)
    idx = np.argsort(-sim, axis=1)[:, :k]
    w = np.take_along_axis(sim, idx, axis=1).clip(min=1e-6)
    return np.einsum("nk,nkd->nd", w, train_y[idx]) / w.sum(axis=1, keepdims=True)


def boost(train_x, train_y, query_x):
    return np.column_stack([
        HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, l2_regularization=1.0,
                                      random_state=0).fit(train_x, train_y[:, j]).predict(query_x)
        for j in range(train_y.shape[1])
    ])


def report(label, pred, truth):
    tol = np.array([SLIDERS[k][0] for k in TARGETS])
    err = np.abs(pred - truth)
    ok = err <= tol
    cells = "".join(f"{err[:, j].mean():>9.2f} ({ok[:, j].mean():>3.0%})" for j in range(len(TARGETS)))
    print(f"{label:<40}{cells}   {ok.all(axis=1).mean():>6.0%}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(sys.argv[1])
    z = np.load(work / "model_lab_features.npz")
    Xtr, Xte = z["tr_hist+stats+face"], z["te_hist+stats+face"]
    Ytr, Yte = z["Ytr"][:, :3], z["Yte"][:, :3]
    e = np.load(work / "dinov2_vits14.npz")["emb"]
    Etr, Ete = e[: len(Ytr)], e[len(Ytr):]
    S = StandardScaler().fit(Xtr)
    Ftr, Fte = S.transform(Xtr), S.transform(Xte)

    print(f"train {len(Ytr)}, test {len(Yte)}\n{'method':<40}{'Exposure':>16}{'Temperature':>18}{'Tint':>14}   all-3 ok")
    report("guess the mean", np.tile(Ytr.mean(axis=0), (len(Yte), 1)), Yte)
    b = boost(Xtr, Ytr, Xte)
    report("v2 model (boosting)", b, Yte)
    for k in (5, 10, 20, 40):
        report(f"retrieval DINOv2, k={k}", knn_predict(Etr, Ytr, Ete, k), Yte)
    for k in (10, 20):
        report(f"retrieval v2 features, k={k}", knn_predict(Ftr, Ytr, Fte, k), Yte)
    r = knn_predict(Etr, Ytr, Ete, 20)
    for w in (0.25, 0.5):
        report(f"blend: {1 - w:.2f} model + {w:.2f} retrieval", (1 - w) * b + w * r, Yte)

    # Stacking: the neighbours' sliders as extra features. Out-of-fold for the training
    # photos, so the model never sees a photo's own value through its neighbours.
    oof = np.zeros_like(Ytr)
    for fit_idx, val_idx in KFold(5, shuffle=True, random_state=0).split(Etr):
        oof[val_idx] = knn_predict(Etr[fit_idx], Ytr[fit_idx], Etr[val_idx], 20)
    report("v2 model + neighbour sliders as features", boost(np.hstack([Xtr, oof]), Ytr,
                                                            np.hstack([Xte, r])), Yte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
