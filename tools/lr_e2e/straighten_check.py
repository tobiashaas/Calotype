"""End-to-end check of "straighten" in a real Lightroom, through the automation channel.

    python tools/lr_e2e/straighten_check.py --profile "LR R6 2031" --previews <dir> --folder 100EOSR6
           [--photos 3] [--out DIR]

Picks photos whose preview has clear reference lines (same estimate as the feature worker),
backs up ALL their develop settings, resets their crop, applies the profile with straighten on,
checks that Lightroom holds our angle and the matching crop, then restores the backup.
A second pass checks that a photo with its own crop keeps it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import Bridge, Report, bridge_config  # noqa: E402

from calotype_inference_pipeline.straighten import crop_settings, estimate_tilt  # noqa: E402

KEYS = ["CropAngle", "CropLeft", "CropTop", "CropRight", "CropBottom"]
FULL = {"CropAngle": 0, "CropLeft": 0, "CropTop": 0, "CropRight": 1, "CropBottom": 1}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--previews", type=Path, required=True, help="Bridge previews named like the RAWs")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--photos", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("lr_e2e_out"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    bridge, report = Bridge(bridge_config()), Report()

    listed = bridge.run("list_photos", {"limit": 100000, "format": "raw"})["photos"]
    by_stem = {Path(p["path"]).stem: p for p in listed
               if a.folder in (p.get("path") or "") and not p.get("virtual_copy") and os.path.exists(p["path"])}
    chosen = []
    for prev in sorted(a.previews.glob("*.jpg")):
        if prev.stem not in by_stem:
            continue
        img = Image.open(prev)
        tilt = estimate_tilt(img)
        if tilt.confident and abs(tilt.crop_angle) >= 0.1:   # level photos need no crop
            chosen.append((by_stem[prev.stem]["uuid"], prev.stem, tilt.crop_angle))
        if len(chosen) > a.photos:
            break
    report.check(len(chosen) > a.photos, f"{a.photos + 1} photos with clear lines", ", ".join(c[1] for c in chosen))
    uuids = [c[0] for c in chosen]

    backup = bridge.run("develop_settings", {"uuids": uuids})["settings"]
    (a.out / "straighten-backup.json").write_text(json.dumps(backup), encoding="utf-8")
    try:
        # All but the last photo: no crop → must be straightened. The last: an own crop → kept.
        own = {"CropAngle": 0.8, "CropLeft": 0.03, "CropTop": 0.02, "CropRight": 0.97, "CropBottom": 0.98}
        reset = {u: dict(FULL) for u in uuids[:-1]}
        reset[uuids[-1]] = own
        bridge.run("set_develop_settings", {"settings": reset})
        r = bridge.run("apply", {"profile": a.profile, "uuids": uuids, "straighten": True}, timeout=1800)
        report.check(r.get("applied") == len(uuids), "every photo got a result", f"{r.get('applied')} of {len(uuids)}")
        report.check(r.get("straightened") == len(uuids) - 1 and r.get("kept_crop") == 1,
                     "uncropped photos straightened, own crop kept",
                     f"straightened {r.get('straightened')}, kept {r.get('kept_crop')}")
        after = bridge.run("develop_settings", {"uuids": uuids, "keys": KEYS})["settings"]
        for uuid, stem, angle in chosen[:-1]:
            got = after[uuid]
            want = crop_settings(angle, 6000, 4000)
            off = max(abs(float(got.get(k) or 0) - float(want[k])) for k in KEYS)
            report.check(off < 0.02, f"{stem}: Lightroom holds angle {angle:+.2f} and its crop",
                         json.dumps({k: got.get(k) for k in KEYS}))
        kept = after[uuids[-1]]
        report.check(all(abs(float(kept.get(k) or 0) - v) < 1e-6 for k, v in own.items()),
                     f"{chosen[-1][1]}: own crop untouched")
    finally:
        now = bridge.run("develop_settings", {"uuids": uuids})["settings"]
        restore = {u: {k: v for k, v in backup[u].items()
                       if json.dumps(v, sort_keys=True) != json.dumps(now[u].get(k), sort_keys=True)}
                   for u in uuids}
        bridge.run("set_develop_settings", {"settings": {u: s for u, s in restore.items() if s}})
        back = bridge.run("develop_settings", {"uuids": uuids})["settings"]
        same = all(json.dumps(back[u].get(k), sort_keys=True) == json.dumps(backup[u].get(k), sort_keys=True)
                   for u in uuids for k in KEYS + ["Exposure2012", "Temperature", "Tint"])
        report.check(same, "original settings restored")

    print(f"\n{'ALL PASSED' if report.failures == 0 else f'{report.failures} FAILED'}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
