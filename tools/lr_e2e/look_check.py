"""End-to-end check of a look from one of the photographer's Lightroom presets.

    python tools/lr_e2e/look_check.py --look "<preset name>" --examples <uuid> <uuid> --targets <uuid> ...

All photos: local RAWs of one shoot, untouched and without masks. The examples get a plain
edit (exposure only, no look); "apply" without a profile, learning from the edits, with the
chosen preset as look must give the targets the preset's look settings (curve, colors, grain …)
while exposure comes from the examples, not from the preset. Everything is restored at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import Bridge, Report, bridge_config  # noqa: E402

from calotype_edit_serializer import style_settings  # noqa: E402

BASE_KEYS = ["Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012",
             "Whites2012", "Blacks2012", "Vibrance", "Saturation", "WhiteBalance"]


def same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) < 1e-3
    except (TypeError, ValueError):
        return a == b


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--look", required=True, help="name or uuid of an installed develop preset")
    ap.add_argument("--examples", nargs=2, required=True)
    ap.add_argument("--targets", nargs="+", required=True)
    a = ap.parse_args()
    bridge, report = Bridge(bridge_config()), Report()
    uuids = a.examples + a.targets

    preset = bridge.run("look_presets", {"name": a.look}).get("settings") or {}
    look = style_settings(preset)
    report.check(bool(look), f"preset {a.look!r}: {len(look)} look settings", ", ".join(sorted(look))[:200])
    keys = sorted(set(BASE_KEYS) | set(look))
    backup = bridge.run("develop_settings", {"uuids": uuids, "keys": keys})["settings"]
    before = bridge.run("retouch_state", {"uuids": uuids})
    report.check(all(before[u]["all_masks"] == 0 for u in uuids), "no masks on the test photos")
    try:
        bridge.run("set_develop_settings", {"settings": {
            a.examples[0]: {"Exposure2012": 0.3}, a.examples[1]: {"Exposure2012": 0.5}}})
        r = bridge.run("apply", {"uuids": uuids, "learn_from_edits": True, "look": a.look}, timeout=1800)
        report.check(r.get("applied") == len(a.targets), "targets edited, examples kept",
                     f"applied {r.get('applied')}: {r.get('text')}")
        got = bridge.run("develop_settings", {"uuids": a.targets, "keys": keys})["settings"]
        for u in a.targets:
            wrong = {k: (v, got[u].get(k)) for k, v in look.items()
                     if k not in ("Vibrance", "Saturation") and not same(v, got[u].get(k))}
            report.check(not wrong, f"{u[:8]}: the preset's look", json.dumps(wrong)[:300])
            report.check(same(got[u].get("Exposure2012"), 0.4), f"{u[:8]}: exposure from the examples",
                         f"{got[u].get('Exposure2012')} (preset: {preset.get('Exposure2012')})")
    finally:
        bridge.run("remove_retouch", {"uuids": uuids})
        # "As Shot" defines Kelvin and tint; writing them as well would make it "Custom".
        restore = {u: {k: v for k, v in s.items()
                       if not (s.get("WhiteBalance") == "As Shot" and k in ("Temperature", "Tint"))}
                   for u, s in backup.items()}
        bridge.run("set_develop_settings", {"settings": restore})
        back = bridge.run("develop_settings", {"uuids": uuids, "keys": keys})["settings"]
        diff = {u: {k: (backup[u].get(k), back.get(u, {}).get(k)) for k in keys
                    if not same(backup[u].get(k), back.get(u, {}).get(k))} for u in uuids}
        diff = {u: d for u, d in diff.items() if d}
        report.check(not diff, "settings restored", json.dumps(diff)[:400])

    print(f"\n{'ALL PASSED' if report.failures == 0 else f'{report.failures} FAILED'}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
