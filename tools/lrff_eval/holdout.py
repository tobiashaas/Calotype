"""Hold-out test on real edits: how close does a profile get to edits it never saw?

    python tools/lrff_eval/holdout.py split <raw_dir> <work_dir> [--test 0.2] [--seed 7]
    lrff-folder train <raw_dir> --name "X" --files-from <work_dir>/train.txt
    lrff-folder apply <raw_dir> --profile "X" --files-from <work_dir>/test.txt --out <work_dir>/pred
    python tools/lrff_eval/holdout.py score <raw_dir> <work_dir>

`split` only reads: it lists RAWs whose sidecar holds develop settings and splits them.
`apply --out` writes predictions into the work folder, so the source folder (e.g. a camera
card or someone's edits) stays untouched. `score` compares predicted against real sidecars.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import read_xmp, score_table  # noqa: E402

RAW_SUFFIXES = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".orf", ".rw2"}
EDITED_KEYS = ("Exposure2012", "Temperature", "IncrementalTemperature", "Contrast2012")


def edited_raws(raw_dir: Path) -> list[Path]:
    out = []
    for p in sorted(raw_dir.iterdir()):
        if p.name.startswith("._") or p.suffix.lower() not in RAW_SUFFIXES:
            continue  # "._x" are macOS metadata files
        sidecar = p.with_suffix(".xmp")
        if sidecar.exists() and any(k in read_xmp(sidecar) for k in EDITED_KEYS):
            out.append(p)
    return out


def split(raw_dir: Path, work: Path, test_share: float, seed: int) -> None:
    raws = edited_raws(raw_dir)
    if len(raws) < 10:
        sys.exit(f"only {len(raws)} edited RAWs in {raw_dir}")
    rng = random.Random(seed)
    names = [p.name for p in raws]
    test = set(rng.sample(names, round(len(names) * test_share)))
    work.mkdir(parents=True, exist_ok=True)
    (work / "train.txt").write_text("\n".join(n for n in names if n not in test) + "\n", encoding="utf-8")
    (work / "test.txt").write_text("\n".join(sorted(test)) + "\n", encoding="utf-8")
    print(f"{len(names)} edited RAWs: {len(names) - len(test)} train, {len(test)} test → {work}")


def score(raw_dir: Path, work: Path) -> int:
    def names(f: str) -> list[str]:
        return [n for n in (work / f).read_text(encoding="utf-8").split() if n]

    train = [read_xmp((raw_dir / n).with_suffix(".xmp")) for n in names("train.txt")]
    rows, missing = [], 0
    for n in names("test.txt"):
        pred = (work / "pred" / n).with_suffix(".xmp")
        if not pred.exists():
            missing += 1
            continue
        rows.append((read_xmp((raw_dir / n).with_suffix(".xmp")), read_xmp(pred)))
    if not rows:
        print("no predictions — run `lrff-folder apply ... --out <work_dir>/pred` first")
        return 1
    print(f"\n{len(rows)} test photos scored ({missing} without prediction), {len(train)} trained on\n")
    summary = score_table(rows, train)
    (work / "score.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("raw_dir", type=Path)
    s.add_argument("work_dir", type=Path)
    s.add_argument("--test", type=float, default=0.2)
    s.add_argument("--seed", type=int, default=7)
    c = sub.add_parser("score")
    c.add_argument("raw_dir", type=Path)
    c.add_argument("work_dir", type=Path)
    a = ap.parse_args()
    if a.cmd == "split":
        split(a.raw_dir, a.work_dir, a.test, a.seed)
        return 0
    return score(a.raw_dir, a.work_dir)


if __name__ == "__main__":
    raise SystemExit(main())
