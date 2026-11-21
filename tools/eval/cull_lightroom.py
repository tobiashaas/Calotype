"""Does Lightroom's assisted culling help our culling? Measured against your own decisions.

    python tools/eval/cull_lightroom.py <catalog.lrcat> <preview_dir> --folder <part of path>
                                        [--cache features.json]

1. In Lightroom: run assisted culling on a shoot you already rated or flagged yourself —
   without "apply flag / rating / label", so your own decisions stay the truth.
2. Previews of the shoot's RAWs (file stem = RAW stem):
   cargo run --release -p calotype-bridge-core --example preview -- <preview_dir> <raws>
3. Run this script (reads the catalog read-only, also while Lightroom has it open).

Truth: your pick flag, else 4–5 stars keep / 1–3 stars not (as `decision_from_metadata`).
Reported as ROC-AUC (0.5 = guessing) on the decided photos:

- without any decisions: our rules, each Lightroom score alone
- learned from decisions (5 folds in shooting order, so near-identical neighbours rarely sit
  on both sides): our features, Lightroom's scores, both together
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from cull_compare import load_or_analyze  # noqa: E402

from calotype_culling import score  # noqa: E402
from calotype_culling.cull import decision_from_metadata  # noqa: E402
from calotype_culling.learned import LIGHTROOM_FEATURES, feature_matrix, lightroom_matrix  # noqa: E402

COLUMNS = {   # our name → (table, column), as the Bridge reads them (catalog.rs LR_SCORES)
    "subject_sharpness": ("AgLibraryImageCullingScore", "subjectSharpnessScore"),
    "eye_sharpness": ("AgLibraryImageCullingScore", "eyeSharpnessScore"),
    "eyes_open_state": ("AgLibraryImageCullingScore", "eyesOpenState"),
    "bad_exposure": ("AgLibraryImageCullingScore", "cleanupBadExposureTopProb"),
    "misfire": ("AgLibraryImageCullingScore", "cleanupMisfireTopProb"),
    "aesthetic": ("AgLibraryImageBestFrameScore", "aestheticScore"),
    "combined": ("AgLibraryImageBestFrameScore", "combinedScore"),
    "face": ("AgLibraryImageBestFrameScore", "faceScore"),
    "frame": ("AgLibraryImageBestFrameScore", "frameScore"),
    "severe_blur": ("AgLibraryImageUndesiredScores", "severe_blur_prob"),
    "over_exposure": ("AgLibraryImageUndesiredScores", "over_exposure_prob"),
    "under_exposure": ("AgLibraryImageUndesiredScores", "under_exposure_prob"),
    "ground_shot": ("AgLibraryImageUndesiredScores", "accidental_ground_shot_prob"),
}


def read_catalog(path: Path, folder: str) -> list[dict]:
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    rows = con.execute(
        """SELECT i.id_local, f.baseName, fo.pathFromRoot, i.rating, i.pick, i.captureTime
           FROM Adobe_images i JOIN AgLibraryFile f ON f.id_local = i.rootFile
           JOIN AgLibraryFolder fo ON fo.id_local = f.folder
           WHERE lower(fo.pathFromRoot) LIKE ? ORDER BY i.captureTime""",
        (f"%{folder.lower()}%",)).fetchall()
    photos = {r[0]: {"stem": r[1], "folder": r[2], "decision": decision_from_metadata(
        {"rating": r[3], "pick_status": int(r[4] or 0)}), "time": r[5], "lightroom": {}} for r in rows}
    tables = {t for t, _ in COLUMNS.values()}
    present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in tables & present:
        cols = [(name, c) for name, (t, c) in COLUMNS.items() if t == table]
        sql = f"SELECT image, {', '.join(c for _, c in cols)} FROM {table} ORDER BY id_local"
        for row in con.execute(sql):
            if row[0] in photos:
                for (name, _), v in zip(cols, row[1:]):
                    if isinstance(v, (int, float)):
                        photos[row[0]]["lightroom"][name] = float(v)
    return list(photos.values())


def auc(y: np.ndarray, s: np.ndarray) -> float:
    return float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def cv_auc(X: np.ndarray, y: np.ndarray, folds: int = 5) -> float:
    """Out-of-fold keep probabilities, folds = contiguous blocks in shooting order."""
    pred = np.zeros(len(y))
    for test in np.array_split(np.arange(len(y)), folds):
        train = np.setdiff1d(np.arange(len(y)), test)
        if len(set(y[train])) < 2:
            pred[test] = 0.5
            continue
        sc = StandardScaler().fit(X[train])
        m = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced").fit(sc.transform(X[train]), y[train])
        pred[test] = m.predict_proba(sc.transform(X[test]))[:, 1]
    return auc(y, pred)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("preview_dir", type=Path)
    ap.add_argument("--folder", required=True, help="part of the shoot's folder path in the catalog")
    ap.add_argument("--cache", type=Path)
    args = ap.parse_args()

    photos = read_catalog(args.catalog, args.folder)
    previews = {p.stem.lower(): p for p in args.preview_dir.glob("*.jpg")}
    photos = [p for p in photos if p["stem"].lower() in previews]
    scored = sum(1 for p in photos if p["lightroom"])
    decided = [i for i, p in enumerate(photos) if p["decision"] is not None]
    print(f"{len(photos)} photos with preview, {scored} scored by Lightroom, {len(decided)} decided by you "
          f"({sum(1 for i in decided if photos[i]['decision'])} keep)")
    if len(decided) < 20 or not scored:
        print("too few decided or scored photos to measure")
        return 1

    feats = load_or_analyze([previews[p["stem"].lower()] for p in photos], args.cache)
    y = np.array([int(bool(photos[i]["decision"])) for i in decided])
    names, lr = lightroom_matrix([p["lightroom"] or None for p in photos])
    ours = feature_matrix(feats)

    print("\nwithout decisions (ROC-AUC on your decided photos)")
    rules = np.array([d.score for d in score(feats)])
    print(f"  our rules                 {auc(y, rules[decided]):.3f}")
    for j, name in enumerate(names):
        print(f"  Lightroom {name:<16}{auc(y, lr[decided, j]):.3f}")
    missing = [n for n in LIGHTROOM_FEATURES if n not in names]
    if missing:
        print(f"  (no usable values for: {', '.join(missing)})")

    print("\nlearned from your decisions (5 folds in shooting order)")
    print(f"  our features              {cv_auc(ours[decided], y):.3f}")
    if lr is not None:
        print(f"  Lightroom scores          {cv_auc(lr[decided], y):.3f}")
        print(f"  both                      {cv_auc(np.hstack([ours, lr])[decided], y):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
