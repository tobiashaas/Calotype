"""Learn culling weights from reference decisions and measure on held-out photos.

    python tools/lrff_eval/cull_learn.py <features.json> <raw_dir> <work_dir>

features.json from `cull_compare.py --cache`; the split from `holdout.py split`
(train.txt / test.txt). Label: keep = 5 stars. Compares the learned scorer with the
hand-set baseline on the same test photos (ROC-AUC, agreement at the reference's keep rate).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from cull_compare import load_or_analyze, ref_bucket, reference  # noqa: E402

from lr_frameflow_culling import score  # noqa: E402
from lr_frameflow_culling.learned import LearnedScorer  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("features", type=Path)
    ap.add_argument("raw_dir", type=Path)
    ap.add_argument("work_dir", type=Path)
    a = ap.parse_args()

    feats = load_or_analyze([], a.features)       # cache only
    names = [Path(f.name).stem for f in feats]
    keep = np.array([ref_bucket(*reference(a.raw_dir, n)) == "keep" for n in names])
    test_names = {Path(n).stem for n in (a.work_dir / "test.txt").read_text(encoding="utf-8").split()}
    is_test = np.array([n in test_names for n in names])

    # Series and ranks are shoot-level context: compute them on the whole shoot, then split.
    scorer = LearnedScorer.fit([f for f, t in zip(feats, is_test) if not t], keep[~is_test].tolist())
    p_all = scorer.keep_probability(feats)
    baseline = np.array([d.score for d in score(feats)])

    y = keep[is_test]
    for label, s in [("baseline (hand weights)", baseline[is_test]), ("learned", p_all[is_test])]:
        auc = roc_auc_score(y, s)
        k = int(y.sum())                           # same keep rate as the reference
        top = np.zeros_like(y)
        top[np.argsort(-s)[:k]] = True
        agree = (top == y).mean()
        rejected_keepers = int((~top & y)[np.argsort(s)[: len(y) // 10]].sum())
        print(f"{label:<26} ROC-AUC {auc:.3f}   agreement at reference keep rate {agree:.0%}   "
              f"reference keeps among our bottom 10 %: {rejected_keepers}")

    print(f"\ntest photos {is_test.sum()}, reference keeps {int(y.sum())} ({y.mean():.0%})")
    print("\nlearned weights (standardized features; + favors keep)")
    for name, w in scorer.weights():
        print(f"  {w:+.2f}  {name}")
    expl = scorer.explain([f for f, t in zip(feats, is_test) if t])
    order = np.argsort(p_all[is_test])
    print("\nexamples (lowest and highest keep probability)")
    test_feats = [f for f, t in zip(feats, is_test) if t]
    for i in list(order[:3]) + list(order[-3:]):
        print(f"  {test_feats[i].name}  p={p_all[is_test][i]:.2f}  ref={'keep' if y[i] else 'no'}   {expl[i]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
