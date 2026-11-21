"""Train a profile in a real Lightroom and score it on held-out photos of the same catalog.

    python tools/lr_e2e/train_eval.py --folder 100EOSR6 --name "LR R6" [--holdout 0.2]
           [--exclude uuids.json] [--max-train N] [--max-eval N] [--out DIR] [--skip-train]

Everything goes through the plugin's automation channel, i.e. the same code as the menu items:
training targets come from photo:getDevelopSettings(), predictions are written with
photo:applyDevelopSettings().

  1. pick edited photos whose file is on disk (path contains --folder, no virtual copies)
  2. split by a hash of the photo UUID: --holdout share is never trained on
  3. train the profile from the rest, wait until it is ready
  4. per batch of held-out photos: back up ALL develop settings to --out, apply the profile,
     read the result, compare with the photo's own edit, restore every key that changed
  5. print the score table (same tolerances as tools/eval)

Your edits are restored after every batch; the backups in --out allow a manual restore.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from common import SLIDERS  # noqa: E402
from run import CHECKED, Bridge, bridge_config  # noqa: E402

TONE = [k for k in CHECKED if k not in ("Temperature", "Tint")]


def edited(s: dict) -> bool:
    return any(abs(float(s.get(k) or 0)) > 1e-6 for k in TONE) or s.get("WhiteBalance") not in (None, "As Shot")


def held_out(uuid: str, share: float) -> bool:
    return int(hashlib.sha1(uuid.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < share


def settings_of(bridge: Bridge, uuids: list[str], keys: list[str] | None = None) -> dict:
    out: dict = {}
    for i in range(0, len(uuids), 200):
        args = {"uuids": uuids[i:i + 200]}
        if keys:
            args["keys"] = keys
        out.update(bridge.run("develop_settings", args)["settings"])
    return out


def same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", required=True, help="part of the photo path, e.g. 100EOSR6")
    ap.add_argument("--name", required=True, help="profile name")
    ap.add_argument("--genre", default="event")
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--exclude", help="JSON list of UUIDs to leave out (e.g. photos edited by a model)")
    ap.add_argument("--max-train", type=int, default=0)
    ap.add_argument("--max-eval", type=int, default=0)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--out", default="lr_e2e_out")
    ap.add_argument("--skip-train", action="store_true", help="profile --name exists already: only score it")
    a = ap.parse_args()

    bridge = Bridge(bridge_config())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    excluded = set(json.loads(Path(a.exclude).read_text())) if a.exclude else set()

    listed = bridge.run("list_photos", {"limit": 100000, "format": "raw"})["photos"]
    pool = [p for p in listed if a.folder in (p.get("path") or "") and not p.get("virtual_copy")
            and p["uuid"] not in excluded and os.path.exists(p["path"])]
    targets = settings_of(bridge, [p["uuid"] for p in pool], CHECKED + ["WhiteBalance"])
    pool = [p for p in pool if edited(targets.get(p["uuid"], {}))]
    train = [p["uuid"] for p in pool if not held_out(p["uuid"], a.holdout)]
    test = [p["uuid"] for p in pool if held_out(p["uuid"], a.holdout)]
    if a.max_train:
        train = train[: a.max_train]
    if a.max_eval:
        test = test[: a.max_eval]
    print(f"{len(pool)} edited photos in '{a.folder}': train {len(train)}, held out {len(test)}", flush=True)

    if not a.skip_train:
        t0 = time.time()
        trained = bridge.run("train", {"uuids": train, "name": a.name, "genre": a.genre}, timeout=4 * 3600)
        print(f"train: {trained.get('title')} — {time.time() - t0:.0f} s", flush=True)
        if not trained.get("ok"):
            print(trained.get("text"))
            return 1

    preds, truth = {}, {}
    for i in range(0, len(test), a.batch):
        batch = test[i:i + a.batch]
        before = settings_of(bridge, batch)
        (out / f"backup-{a.name}-{i:05d}.json").write_text(json.dumps(before), encoding="utf-8")
        applied = bridge.run("apply", {"profile": a.name, "uuids": batch}, timeout=3600)
        after = settings_of(bridge, batch)
        restore = {u: {k: before[u][k] for k in before[u] if not same(before[u].get(k), after[u].get(k))}
                   for u in batch if u in before}
        bridge.run("set_develop_settings", {"settings": {u: s for u, s in restore.items() if s}})
        back = settings_of(bridge, batch, CHECKED + ["WhiteBalance"])
        bad = [u for u in batch if any(not same(back[u].get(k), before[u].get(k)) for k in CHECKED)]
        for u in applied.get("applied_uuids") or []:
            preds[u], truth[u] = after[u], before[u]
        print(f"  batch {i // a.batch + 1}: applied {applied.get('applied')} of {len(batch)}, "
              f"restored {'all' if not bad else f'all but {len(bad)}'}", flush=True)
        if bad:
            print("  RESTORE INCOMPLETE — backups in", out, bad[:5])
            return 1

    train_t = settings_of(bridge, train, CHECKED)
    rows, ok_all = [], np.ones(len(preds), bool)
    print(f"\n{'slider':<16}{'model MAE':>11}{'guess-mean MAE':>16}{'within tol.':>13}   tolerance")
    for k, (tol, unit) in SLIDERS.items():
        y = np.array([float(truth[u].get(k) or 0) for u in preds])
        p = np.array([float(preds[u].get(k) or 0) for u in preds])
        mean = np.mean([float(s.get(k) or 0) for s in train_t.values()])
        err = np.abs(p - y)
        within = err <= tol
        ok_all &= within
        rows.append({"slider": k, "mae": err.mean(), "guess_mae": np.abs(mean - y).mean(), "within": within.mean()})
        print(f"{k:<16}{err.mean():>11.2f}{np.abs(mean - y).mean():>16.2f}{within.mean():>12.0%}   ±{tol:g} {unit}")
    print(f"\nphotos with every slider within tolerance: {ok_all.mean():.0%}  (n = {len(preds)})")
    (out / f"score-{a.name}.json").write_text(json.dumps(
        {"name": a.name, "folder": a.folder, "train": len(train), "test": len(preds),
         "all_within": float(ok_all.mean()), "sliders": rows}, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
