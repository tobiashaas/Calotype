"""Compare the culling prototype with reference decisions stored in XMP sidecars.

    python tools/lrff_eval/cull_compare.py <preview_dir> <raw_dir> [--cache features.json]

Reference = xmp:Rating / xmp:Label next to each RAW (a photographer's ratings, or another
tool's cull for a baseline comparison). Mapping: 5 stars = keep, 1–2 stars or a red/purple
label = reject, everything else = maybe. Reported:

- agreement of our keep / uncertain / reject with the reference (confusion matrix)
- per feature: are reference rejects for blur less sharp in our measure? do reference
  rejects for closed eyes show closed eyes for us?

The reference is not ground truth unless it is your own rating — it is a yardstick.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import top_description  # noqa: E402

from lr_frameflow_culling import FaceAnalyzer, analyze, score  # noqa: E402
from lr_frameflow_culling.analyze import PhotoFeatures  # noqa: E402
from lr_frameflow_culling.faces import Face  # noqa: E402

RAW_SUFFIXES = (".CR3", ".CR2", ".NEF", ".ARW", ".RAF", ".DNG")


def reference(raw_dir: Path, stem: str) -> tuple[int | None, str | None]:
    sidecar = raw_dir / f"{stem}.xmp"
    if not sidecar.exists():
        return None, None
    top = top_description(sidecar.read_text(encoding="utf-8", errors="replace"))
    r = re.search(r'xmp:Rating="(-?\d)"', top)
    lab = re.search(r'xmp:Label="([^"]*)"', top)
    return (int(r.group(1)) if r else None), (lab.group(1).lower() if lab else None)


def ref_bucket(rating: int | None, label: str | None) -> str:
    if rating == 5:
        return "keep"
    if (rating is not None and rating <= 2) or label in {"red", "purple"}:
        return "reject"
    return "maybe"


def load_or_analyze(previews: list[Path], cache: Path | None) -> list[PhotoFeatures]:
    if cache and cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8"))
        out = []
        for d in raw:
            faces = [Face(box=tuple(f["box"]), score=f["score"], rel_size=f["rel_size"],
                          sharpness=f["sharpness"], eyes_closed=f["eyes_closed"], smile=f["smile"],
                          mouth_open=f["mouth_open"]) for f in d["faces"]]
            out.append(PhotoFeatures(
                name=d["name"], width=d["width"], height=d["height"], sharpness=d["sharpness"],
                center_sharpness=d["center_sharpness"], mean_luma=d["mean_luma"],
                clipped_highlights=d["clipped_highlights"], crushed_shadows=d["crushed_shadows"],
                dhash=int(d["dhash"], 16), faces=faces, face_clipped=d.get("face_clipped", 0.0)))
        print(f"loaded {len(out)} cached feature sets from {cache}")
        return out
    t0 = time.perf_counter()
    feats = []
    with FaceAnalyzer() as fa:
        for i, p in enumerate(previews, 1):
            feats.append(analyze(p, fa))
            if i % 200 == 0:
                print(f"  analyzed {i}/{len(previews)}")
    dt = time.perf_counter() - t0
    print(f"analyzed {len(feats)} photos in {dt:.0f} s ({1000 * dt / len(feats):.0f} ms/photo)")
    if cache:
        data = []
        for f in feats:
            d = f.to_dict()
            d["face_clipped"] = f.face_clipped
            data.append(d)
        cache.write_text(json.dumps(data), encoding="utf-8")
    return feats


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preview_dir", type=Path)
    ap.add_argument("raw_dir", type=Path)
    ap.add_argument("--cache", type=Path)
    a = ap.parse_args()

    previews = sorted(p for p in a.preview_dir.iterdir() if p.suffix.lower() == ".jpg")
    feats = load_or_analyze(previews, a.cache)
    decisions = score(feats)
    refs = [reference(a.raw_dir, Path(f.name).stem) for f in feats]
    ref_b = [ref_bucket(r, lab) for r, lab in refs]
    ours = [d.bucket for d in decisions]

    print(f"\nreference: {dict(Counter(ref_b))}   ours: {dict(Counter(ours))}")
    print("\nconfusion (rows = reference, columns = ours)")
    cols = ["keep", "uncertain", "reject"]
    print(f"{'':>10}" + "".join(f"{c:>11}" for c in cols))
    for r in ["keep", "maybe", "reject"]:
        counts = Counter(o for o, rb in zip(ours, ref_b) if rb == r)
        total = sum(counts.values()) or 1
        print(f"{r:>10}" + "".join(f"{counts[c]:>6} {counts[c] / total:>4.0%}" for c in cols))

    keep_ref = np.array([b == "keep" for b in ref_b])
    keep_ours = np.array([o == "keep" for o in ours])
    rej_ref = np.array([b == "reject" for b in ref_b])
    rej_ours = np.array([o == "reject" for o in ours])

    def pr(pred, truth):
        tp = (pred & truth).sum()
        return tp / max(pred.sum(), 1), tp / max(truth.sum(), 1)

    kp, kr = pr(keep_ours, keep_ref)
    rp, rr = pr(rej_ours, rej_ref)
    print(f"\nkeep:   precision {kp:.0%} (our keeps the reference also keeps), recall {kr:.0%}")
    print(f"reject: precision {rp:.0%}, recall {rr:.0%}")
    hard = (rej_ours & keep_ref).sum()
    print(f"we reject a reference keep: {hard} photos ({hard / max(keep_ref.sum(), 1):.1%} of its keeps)")

    print("\nfeatures vs. reference reasons")
    sharp = np.array([f.subject_sharpness for f in feats])
    pct = sharp.argsort().argsort() / max(len(sharp) - 1, 1)
    labels = np.array([lab for _, lab in refs], dtype=object)
    for name, mask in [("red (blur)", labels == "red"), ("purple (eyes)", labels == "purple"),
                       ("green (keep)", labels == "green")]:
        if mask.sum() == 0:
            continue
        closed = np.array([(f.eyes_closed or 0) > 0.6 for f in feats])
        no_face = np.array([not f.faces for f in feats])
        print(f"  {name:<14} n={mask.sum():>4}  sharpness percentile median {np.median(pct[mask]):.2f}  "
              f"eyes closed {closed[mask].mean():.0%}  no face {no_face[mask].mean():.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
