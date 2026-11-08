"""End-to-end check of retouch (Lightroom AI masks) in a real Lightroom.

    python tools/lr_e2e/retouch_check.py --profile "LR R6 2031" --folder 100EOSR6

Applies a profile with retouch to two photos without masks and one with a mask of its own,
then checks: Lightroom computed our masks (or removed the ones with nothing to find), the
photo's own mask is untouched, the original is kept as a snapshot, a second run does not
duplicate masks. Everything is removed and restored at the end. Needs the Bridge to have
installed the presets and Lightroom restarted once afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import Bridge, Report, bridge_config  # noqa: E402

RETOUCH = ["subject", "eyes", "teeth", "sky"]
KEYS = ["Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012",
        "Blacks2012", "Vibrance", "Saturation", "WhiteBalance"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--folder", required=True)
    a = ap.parse_args()
    bridge, report = Bridge(bridge_config()), Report()

    listed = [p for p in bridge.run("list_photos", {"limit": 100000, "format": "raw"})["photos"]
              if a.folder in (p.get("path") or "") and not p.get("virtual_copy")]
    listed.sort(key=lambda p: p["path"])
    head = [p["uuid"] for p in listed[:40]]   # reading masks is slow in Lightroom
    masks = bridge.run("develop_settings", {"uuids": head, "keys": ["MaskGroupBasedCorrections"]})["settings"]
    without = [u for u in head if not masks.get(u, {}).get("MaskGroupBasedCorrections")]
    with_own = [u for u in head if masks.get(u, {}).get("MaskGroupBasedCorrections")]
    uuids = without[:2] + with_own[:1]
    report.check(len(uuids) == 3, "two photos without masks, one with its own mask")
    before = bridge.run("retouch_state", {"uuids": uuids})
    backup = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]

    try:
        for run in (1, 2):
            r = bridge.run("apply", {"profile": a.profile, "uuids": uuids, "retouch": RETOUCH}, timeout=1800)
            m = r.get("masks") or {}
            report.check(r.get("applied") == 3 and m.get("added") == 3 * len(RETOUCH),
                         f"run {run}: profile applied, retouch masks added", json.dumps(m))
            report.check(m.get("pending") == 0 and m.get("found", 0) >= 2,
                         f"run {run}: Lightroom computed the masks", f"found {m.get('found')}, "
                         f"nothing to find {m.get('removed')}, pending {m.get('pending')}")
        state = bridge.run("retouch_state", {"uuids": uuids})
        for u in uuids:
            ours = state[u]["masks"]
            names = [g["name"] for g in ours]
            report.check(len(names) == len(set(names)) and "Tarsier subject" in names,
                         "no duplicates after two runs, subject mask present", ", ".join(names))
            report.check(all(g["computed"] == g["masks"] for g in ours), "every kept mask is computed")
            report.check(state[u]["all_masks"] - len(ours) == before[u]["all_masks"],
                         "the photo's own masks are untouched")
            report.check("Tarsier: before" in state[u]["snapshots"] or "Tarsier: vorher" in state[u]["snapshots"],
                         "original kept as snapshot")
    finally:
        bridge.run("remove_retouch", {"uuids": uuids})
        bridge.run("set_develop_settings", {"settings": backup})
        after = bridge.run("retouch_state", {"uuids": uuids})
        back = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]
        report.check(all(after[u]["all_masks"] == before[u]["all_masks"] and not after[u]["masks"] for u in uuids),
                     "our masks removed, own masks still there")
        report.check(json.dumps(back, sort_keys=True) == json.dumps(backup, sort_keys=True), "settings restored")

    print(f"\n{'ALL PASSED' if report.failures == 0 else f'{report.failures} FAILED'}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
