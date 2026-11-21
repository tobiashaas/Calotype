"""End-to-end check of learned mask strengths in a real Lightroom.

    python tools/lr_e2e/mask_strength_check.py --examples <uuid> <uuid> --targets <uuid> <uuid>

All photos: local RAWs of one shoot, untouched (the same develop settings) and without masks.
The examples get an edit (different exposures) and a subject mask with set strengths; then
"apply" without a profile, learning from the edits, must give the targets our subject mask,
computed by Lightroom, with the examples' strengths. Everything is restored at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import Bridge, Report, bridge_config  # noqa: E402

STRENGTHS = {"LocalShadows2012": 0.25, "LocalHighlights2012": -0.15}
KEYS = ["Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012",
        "Blacks2012", "Vibrance", "Saturation", "WhiteBalance"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--examples", nargs=2, required=True)
    ap.add_argument("--targets", nargs="+", required=True)
    a = ap.parse_args()
    bridge, report = Bridge(bridge_config()), Report()
    uuids = a.examples + a.targets

    before = bridge.run("retouch_state", {"uuids": uuids})
    backup = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]
    report.check(all(before[u]["all_masks"] == 0 for u in uuids), "no masks on the test photos")
    try:
        bridge.run("set_develop_settings", {"settings": {
            a.examples[0]: {"Exposure2012": 0.3}, a.examples[1]: {"Exposure2012": 0.5}}})
        r = bridge.run("set_mask_strength", {"uuids": a.examples, "strengths": {"subject": STRENGTHS}}, timeout=600)
        report.check(r.get("set") == 2, "examples: subject mask with set strengths", json.dumps(r))

        r = bridge.run("apply", {"uuids": uuids, "learn_from_edits": True}, timeout=1800)
        m = r.get("masks") or {}
        report.check(r.get("applied") == len(a.targets), "targets edited, examples kept",
                     f"applied {r.get('applied')}: {r.get('text')}")
        report.check(m.get("added") == len(a.targets) and m.get("learned", 0) + m.get("removed", 0) == len(a.targets),
                     "learned subject mask added to the targets", json.dumps(m))
        state = bridge.run("retouch_state", {"uuids": a.targets})
        for u in a.targets:
            ours = state[u]["masks"]
            if not ours:
                report.check(True, f"{u[:8]}: no subject found, mask removed")
                continue
            g = ours[0]
            report.check(g["name"] == "Calotype subject" and g["computed"] == g["masks"],
                         f"{u[:8]}: our subject mask, computed by Lightroom", json.dumps(g))
        values = bridge.run("develop_settings", {"uuids": a.targets, "keys": ["MaskGroupBasedCorrections"]})["settings"]
        for u in a.targets:
            for grp in values[u].get("MaskGroupBasedCorrections") or []:
                if grp.get("CorrectionName") == "Calotype subject":
                    got = {k: round(float(grp.get(k, 0)), 3) for k in STRENGTHS}
                    report.check(got == STRENGTHS, f"{u[:8]}: the examples' strengths", json.dumps(got))
    finally:
        bridge.run("remove_retouch", {"uuids": uuids})
        # "As Shot" defines Kelvin and tint; writing them as well would make it "Custom".
        restore = {u: {k: v for k, v in s.items()
                       if not (s.get("WhiteBalance") == "As Shot" and k in ("Temperature", "Tint"))}
                   for u, s in backup.items()}
        bridge.run("set_develop_settings", {"settings": restore})
        after = bridge.run("retouch_state", {"uuids": uuids})
        back = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]
        report.check(all(not after[u]["masks"] for u in uuids), "our masks removed")
        diff = {u: {k: (backup[u].get(k), back.get(u, {}).get(k)) for k in KEYS
                    if backup[u].get(k) != back.get(u, {}).get(k)} for u in uuids}
        diff = {u: d for u, d in diff.items() if d}
        report.check(not diff, "settings restored", json.dumps(diff))

    print(f"\n{'ALL PASSED' if report.failures == 0 else f'{report.failures} FAILED'}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
