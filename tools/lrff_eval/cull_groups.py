"""Culling measured against a photographer's real choice, one whole group held out at a time.

    python tools/lrff_eval/cull_groups.py <work_dir> <labels.json> [--groups A B ...]

<work_dir>/<group>/features.json from `cull_compare.py --cache` (one shoot or group each).
labels.json: {group: {file stem: {"rating": int, "label": str, "exported": bool}}}

- reference = "exported" (what was delivered) — the photographer's own decision
- weak label = another tool's cull (5 stars = keep), used only for training

Leave-one-group-out: train on all other groups, test on the held-out one, so photos of the same
people never sit on both sides. Groups where everything (or nothing) was exported carry no
signal for the reference and are only used for training. Reported per test group, ROC-AUC
against "exported" for: hand weights, learned from the weak labels, learned from the reference,
and the other tool's own rating as a score.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from cull_compare import load_or_analyze  # noqa: E402

from lr_frameflow_culling import score  # noqa: E402
from lr_frameflow_culling.learned import LearnedScorer  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("labels", type=Path)
    ap.add_argument("--groups", nargs="*")
    a = ap.parse_args()

    labels = json.loads(a.labels.read_text(encoding="utf-8"))
    groups = a.groups or sorted(p.parent.name for p in a.work_dir.glob("*/features.json"))
    data = {}
    for g in groups:
        feats = load_or_analyze([], a.work_dir / g / "features.json")
        lab = labels.get(g, {})
        feats = [f for f in feats if Path(f.name).stem in lab]
        info = [lab[Path(f.name).stem] for f in feats]
        data[g] = {
            "feats": feats,
            "weak": np.array([(i.get("rating") or 0) >= 5 for i in info]),
            "ref": np.array([bool(i.get("exported")) for i in info]),
            "rating": np.array([float(i.get("rating") or 0) for i in info]),
        }
        d = data[g]
        print(f"{g:<10} {len(feats):5d} photos  weak keep {d['weak'].mean():4.0%}  exported {d['ref'].mean():4.0%}")

    print(f"\n{'held out':<10}{'n':>6}{'exp.':>6}{'hand':>8}{'weak→':>8}{'ref→':>8}{'other tool':>12}")
    rows = []
    for g in groups:
        test = data[g]
        if test["ref"].all() or not test["ref"].any():
            continue
        train = [h for h in groups if h != g]
        tf = [f for h in train for f in data[h]["feats"]]
        weak = LearnedScorer.fit(tf, np.concatenate([data[h]["weak"] for h in train]).tolist())
        ref_groups = [h for h in train if 0 < data[h]["ref"].mean() < 1]
        ref = LearnedScorer.fit([f for h in ref_groups for f in data[h]["feats"]],
                                np.concatenate([data[h]["ref"] for h in ref_groups]).tolist())
        y = test["ref"]
        scores = {
            "hand": np.array([d.score for d in score(test["feats"])]),
            "weak": weak.keep_probability(test["feats"]),
            "ref": ref.keep_probability(test["feats"]),
            "tool": test["rating"],
        }
        auc = {k: roc_auc_score(y, s) for k, s in scores.items()}
        rows.append(auc)
        print(f"{g:<10}{len(y):>6}{y.mean():>6.0%}{auc['hand']:>8.3f}{auc['weak']:>8.3f}{auc['ref']:>8.3f}"
              f"{auc['tool']:>12.3f}")
    if rows:
        mean = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
        print(f"{'mean':<10}{'':>12}{mean['hand']:>8.3f}{mean['weak']:>8.3f}{mean['ref']:>8.3f}{mean['tool']:>12.3f}")
        print("\nROC-AUC against what was exported (0.5 = chance). weak→ = learned from the other tool's "
              "stars, ref→ = learned from the exports of the other groups.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
