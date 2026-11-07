"""End-to-end test in a real, running Lightroom — through the plugin's automation channel.

    python tools/lr_e2e/run.py --profile "Benchmark R6 v2" [--photos 5] [--train 20]

Requirements: Bridge running with "automation": true in bridge.json, Lightroom open with the
LR-FrameFlow plugin loaded (after enabling, reload the plugin once). Use a test catalog.

Scenario:
  1. ping            — plugin version, Lightroom version, UI language, photo count
  2. list_photos     — pick RAW photos
  3. snapshot        — read their develop settings
  4. apply           — apply the profile with the same code as the menu item
  5. verify          — settings in Lightroom equal what the server predicted,
                       white balance switched to Custom
  6. restore         — write the snapshot back, verify
  7. train (opt.)    — train a profile from N photos, check it becomes ready
Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHECKED = ["Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012",
           "Blacks2012", "Temperature", "Tint", "Vibrance", "Saturation"]


def bridge_config() -> dict:
    base = os.environ.get("LRFF_BRIDGE_DATA_DIR") or str(Path(os.environ.get("APPDATA", "~")) / "LRFrameFlow")
    return json.loads((Path(base) / "bridge.json").read_text(encoding="utf-8"))


class Bridge:
    def __init__(self, cfg: dict):
        self.base = f"http://127.0.0.1:{cfg['port']}"
        self.token = cfg["token"]

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-LRFF-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def run(self, command: str, args: dict | None = None, timeout: float = 600):
        status, cmd = self.call("POST", "/v1/automation/commands", {"command": command, "args": args or {}})
        if status != 202:
            raise RuntimeError(f"{command}: bridge answered {status}: {cmd}")
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, state = self.call("GET", f"/v1/automation/commands/{cmd['id']}")
            if state["status"] == "done":
                if not state["ok"]:
                    raise RuntimeError(f"{command} failed in Lightroom: {state['result']}")
                return state["result"]
            time.sleep(1)
        raise TimeoutError(f"{command}: no answer from Lightroom within {timeout:.0f} s")


class Report:
    def __init__(self):
        self.failures = 0

    def check(self, ok: bool, what: str, detail: str = ""):
        print(f"  {'PASS' if ok else 'FAIL'}  {what}{('  — ' + detail) if detail else ''}")
        self.failures += 0 if ok else 1


def close(a, b, key) -> bool:
    if a is None or b is None:
        return a == b
    tol = 0.011 if key == "Exposure2012" else 0.6
    return abs(float(a) - float(b)) <= tol


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="ready profile (name or id) to apply")
    ap.add_argument("--photos", type=int, default=5)
    ap.add_argument("--train", type=int, default=0, help="also train a profile from N photos")
    a = ap.parse_args()

    bridge = Bridge(bridge_config())
    report = Report()

    _, status = bridge.call("GET", "/v1/automation/status")
    if not status or not status.get("enabled"):
        print('automation is off — set "automation": true in bridge.json and restart the Bridge')
        return 2
    idle = status.get("plugin_idle_secs")
    if idle is None or idle > 15:
        print("Lightroom does not poll — open Lightroom and reload the LR-FrameFlow plugin "
              "(File > Plug-in Manager > Reload Plug-in)")
        return 2

    print("1. ping")
    ping = bridge.run("ping")
    print(f"     Lightroom {ping.get('lightroom')}, plugin {ping['plugin']}, language {ping['language']}, "
          f"{ping['photos']} photos in {ping['catalog']}")
    report.check(ping["photos"] > 0, "catalog has photos")

    print("2. list_photos")
    listed = bridge.run("list_photos", {"limit": 5000, "format": "raw"})
    # Files must be on disk: an offline file (OneDrive, unplugged drive) is skipped by the
    # Bridge after a minute, which is tested in the Bridge's own tests, not here.
    originals = [p for p in listed["photos"]
                 if not p.get("virtual_copy") and p.get("path") and os.path.exists(p["path"])]
    pool = originals or listed["photos"]
    report.check(len(pool) >= a.photos, f"at least {a.photos} RAW photos", f"{len(pool)} found")
    step = max(1, len(pool) // max(1, a.photos))
    chosen = [p["uuid"] for p in pool[::step][: a.photos]]
    bridge.run("select", {"uuids": chosen})

    print("3. snapshot")
    before = bridge.run("develop_settings", {"uuids": chosen})["settings"]
    report.check(len(before) == len(chosen), "settings readable for every photo")

    print(f"4. apply \"{a.profile}\" to {len(chosen)} photos")
    t0 = time.time()
    applied = bridge.run("apply", {"profile": a.profile, "uuids": chosen})
    report.check(applied.get("applied") == len(chosen), "every photo got a result",
                 f"{applied.get('applied')} of {len(chosen)} in {time.time() - t0:.0f} s")

    print("5. verify against the server's prediction")
    _, job = bridge.call("GET", f"/v1/jobs/{applied['job_id']}")
    predicted = {r["lr_catalog_uuid"]: r["lr_settings"] for r in job.get("results") or []}
    after = bridge.run("develop_settings", {"uuids": chosen})["settings"]
    mismatches = []
    for uuid in chosen:
        for key, value in predicted.get(uuid, {}).items():
            if key in CHECKED and not close(after.get(uuid, {}).get(key), value, key):
                mismatches.append(f"{uuid[:8]} {key}: Lightroom {after.get(uuid, {}).get(key)} vs predicted {value}")
    report.check(not mismatches, "Lightroom holds exactly the predicted sliders",
                 "; ".join(mismatches[:3]) + (" …" if len(mismatches) > 3 else ""))
    wb = {after.get(u, {}).get("WhiteBalance") for u in chosen}
    report.check(wb == {"Custom"}, "white balance is Custom after applying", f"seen: {sorted(map(str, wb))}")
    changed = sum(1 for u in chosen for k in CHECKED if not close(after[u].get(k), before[u].get(k), k))
    report.check(changed > 0, "the profile actually changed something", f"{changed} slider values changed")

    print("6. restore")
    restore = {u: {k: before[u].get(k) for k in CHECKED + ["WhiteBalance"] if before[u].get(k) is not None}
               for u in chosen}
    bridge.run("set_develop_settings", {"settings": restore})
    back = bridge.run("develop_settings", {"uuids": chosen})["settings"]
    off = [f"{u[:8]} {k}" for u in chosen for k in CHECKED if not close(back[u].get(k), before[u].get(k), k)]
    report.check(not off, "original settings restored", ", ".join(off[:5]))

    if a.train:
        print(f"7. train from {a.train} photos")
        uuids = [p["uuid"] for p in pool[: a.train]]
        name = f"E2E {time.strftime('%Y-%m-%d %H:%M')}"
        trained = bridge.run("train", {"uuids": uuids, "name": name, "genre": "event"}, timeout=1800)
        report.check(bool(trained.get("ok")), f"profile \"{name}\" trained", trained.get("text") or "")
        _, profiles = bridge.call("GET", "/v1/profiles")
        report.check(any(p["name"] == name and p["status"] == "ready" for p in profiles or []),
                     "profile is ready on the server")

    print(f"\n{'ALL PASSED' if report.failures == 0 else f'{report.failures} FAILED'}")
    return 0 if report.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
