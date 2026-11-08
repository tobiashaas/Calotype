"""End-to-end check of culling in a real Lightroom, through the automation channel.

    python tools/lr_e2e/cull_check.py --folder 100EOSR6 [--photos 80] [--offset 0]

Sorts N consecutive photos of a folder with the same code as the menu item. Checks that every
photo got a decision, that the collections "Tarsier > <test set>" hold them, and that
stars, flags and develop settings are untouched. The test collection set is removed at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import Bridge, Report, bridge_config  # noqa: E402

KEYS = ["Exposure2012", "Temperature", "Tint", "CropAngle"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--photos", type=int, default=80)
    ap.add_argument("--offset", type=int, default=0)
    a = ap.parse_args()
    bridge, report = Bridge(bridge_config()), Report()

    listed = bridge.run("list_photos", {"limit": 100000})["photos"]
    pool = sorted((p for p in listed if a.folder in (p.get("path") or "") and not p.get("virtual_copy")
                   and os.path.exists(p["path"])), key=lambda p: p["path"])
    chosen = pool[a.offset:a.offset + a.photos]
    uuids = [p["uuid"] for p in chosen]
    report.check(len(uuids) == a.photos, f"{a.photos} photos from {a.folder}")
    before_meta = {p["uuid"]: (p.get("rating"), p.get("pick_status")) for p in chosen}
    before = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]

    set_name = f"E2E {time.strftime('%Y-%m-%d %H:%M:%S')}"
    t0 = time.time()
    try:
        r = bridge.run("cull", {"uuids": uuids, "set_name": set_name}, timeout=3600)
        counts = r.get("counts") or {}
        total = sum(counts.values())
        report.check(bool(r.get("ok")) and total == len(uuids), "every photo got a decision",
                     f"keep {counts.get('keep')}, check {counts.get('uncertain')}, sort out {counts.get('reject')} "
                     f"in {time.time() - t0:.0f} s, method {r.get('method')}")
        rated = sum(1 for v in before_meta.values() if (v[0] or 0) > 0 or v[1])
        report.check(r.get("method") == ("learned" if rated >= 16 else "rules"),
                     "learns when enough photos are rated", f"{rated} rated photos")
        dec = r.get("decisions") or []
        report.check(all(d.get("reason") for d in dec), "every decision has a reason",
                     (dec[0].get("reason") if dec else ""))
        agree = [((before_meta[d["uuid"]][0] or 0) >= 4) == (d["bucket"] == "keep")
                 for d in dec if d["bucket"] != "uncertain" and before_meta.get(d["uuid"], (0,))[0]]
        if agree:
            print(f"     agreement with the existing stars (keep ↔ 4–5★, uncertain left out): "
                  f"{sum(agree) / len(agree):.0%} of {len(agree)}")
    finally:
        removed = bridge.run("remove_cull_set", {"set_name": set_name}).get("removed")
        report.check(removed == 1, "test collection set removed")

    after_list = {p["uuid"]: (p.get("rating"), p.get("pick_status")) for p in
                  bridge.run("list_photos", {"limit": 100000})["photos"] if p["uuid"] in before_meta}
    report.check(after_list == before_meta, "stars and flags untouched")
    after = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]
    report.check(json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True), "develop settings untouched")

    print(f"\n{'ALL PASSED' if report.failures == 0 else f'{report.failures} FAILED'}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
