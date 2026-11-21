"""Local Calotype Bridge Server for Adobe Lightroom Classic.

Provides the local Bridge HTTP API on 127.0.0.1:47600 so that the Calotype
Lightroom plugin (Calotype.lrplugin) can edit photos with GPU neural inference
directly from within Lightroom Classic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
import uuid

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import uvicorn

# Calotype imports
from calotype_inference_pipeline.neural import (
    PRESET_BIAS,
    PRESET_LOOKS,
    PRESET_MODELS,
    CalotypeNeuralEngine,
)

CONFIG_PATH = Path(os.environ.get("APPDATA", "")) / "Calotype" / "bridge.json"
DEFAULT_PORT = 47600
DEFAULT_TOKEN = "2db38bbfb0b6450cacf4f6feedaf08c355211795581f400aa5755dbcbaa3d9a2"
PREVIEW_EXE = Path(r"C:\Github\LR-FrameFlow\apps\bridge\target\release\examples\preview.exe")
PREVIEW_CACHE = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\haast\AppData\Local")) / "Calotype" / "previews"
RAW_EXTS = {
    ".cr2", ".cr3",          # Canon
    ".nef", ".nrw",          # Nikon
    ".arw",                  # Sony
    ".raf",                  # Fujifilm
    ".dng", ".rwl",          # Leica / Universal / Apple ProRAW
    ".orf",                  # Olympus / OM System
    ".rw2",                  # Panasonic / Lumix
    ".pef",                  # Pentax
    ".3fr", ".fff",          # Hasselblad
}

# In-memory storage for the active Lightroom session
photos_db: dict[str, dict[str, Any]] = {}
jobs_db: dict[str, dict[str, Any]] = {}

# Cached engine instances per preset
_engines: dict[str, CalotypeNeuralEngine] = {}
_engine_lock = threading.Lock()


def get_engine(preset_name: str) -> CalotypeNeuralEngine:
    with _engine_lock:
        key = preset_name.lower().replace("_", "-")
        if key not in _engines:
            print(f"[Calotype Bridge] Initializing neural engine for preset '{key}' on GPU...", flush=True)
            _engines[key] = CalotypeNeuralEngine(preset=key)
        return _engines[key]


# Catalog of available presets for Lightroom's "Apply profile" dialog
AVAILABLE_PROFILES = [
    {
        "profile_id": "wedding-v6-raw",
        "name": "Wedding v6",
        "genre": "Hochzeit",
        "format_type": "raw",
        "preset_key": "wedding",
        "status": "ready",
        "version": 6,
    },
    {
        "profile_id": "wedding-v6-jpg",
        "name": "Wedding v6",
        "genre": "Hochzeit",
        "format_type": "jpeg_tiff",
        "preset_key": "wedding",
        "status": "ready",
        "version": 6,
    },
    {
        "profile_id": "wedding-herbst-raw",
        "name": "Wedding Herbst VS",
        "genre": "Hochzeit",
        "format_type": "raw",
        "preset_key": "wedding-herbst-vs",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "wedding-herbst-jpg",
        "name": "Wedding Herbst VS",
        "genre": "Hochzeit",
        "format_type": "jpeg_tiff",
        "preset_key": "wedding-herbst-vs",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "kita-raw",
        "name": "KiTa & Familie",
        "genre": "Porträt",
        "format_type": "raw",
        "preset_key": "kita",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "kita-jpg",
        "name": "KiTa & Familie",
        "genre": "Porträt",
        "format_type": "jpeg_tiff",
        "preset_key": "kita",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "peaky-blinders-raw",
        "name": "Peaky Blinders",
        "genre": "Porträt",
        "format_type": "raw",
        "preset_key": "peaky-blinders",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "vintage-sunbeam-raw",
        "name": "Vintage Sunbeam",
        "genre": "Porträt",
        "format_type": "raw",
        "preset_key": "vintage-sunbeam",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "luminous-dream-raw",
        "name": "Luminous Dream",
        "genre": "Porträt",
        "format_type": "raw",
        "preset_key": "luminous-dream",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "eternal-essence-raw",
        "name": "Eternal Essence",
        "genre": "Porträt",
        "format_type": "raw",
        "preset_key": "eternal-essence",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "classic-depths-bw-raw",
        "name": "Classic Depths BW",
        "genre": "Schwarzweiß",
        "format_type": "raw",
        "preset_key": "classic-depths-bw",
        "status": "ready",
        "version": 2,
    },
    {
        "profile_id": "gentle-mist-bw-raw",
        "name": "Gentle Mist BW",
        "genre": "Schwarzweiß",
        "format_type": "raw",
        "preset_key": "gentle-mist-bw",
        "status": "ready",
        "version": 2,
    },
]

app = FastAPI(title="Calotype Local Bridge")


def ensure_config():
    """Ensure bridge.json exists and matches our configuration."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = {
        "port": DEFAULT_PORT,
        "token": DEFAULT_TOKEN,
        "api_base_url": f"http://127.0.0.1:{DEFAULT_PORT}",
        "automation": True,
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[Calotype Bridge] Configuration ready at {CONFIG_PATH}")


def sync_presets_to_camera_raw():
    """Syncs project presets to %APPDATA%/Adobe/CameraRaw/Settings/Calotype."""
    try:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return
        target_dir = Path(appdata) / "Adobe" / "CameraRaw" / "Settings" / "Calotype"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "retouch").mkdir(parents=True, exist_ok=True)

        repo_presets = Path(r"C:\Github\LR-FrameFlow\presets")
        if not repo_presets.exists():
            return

        synced = 0
        for xmp_file in repo_presets.glob("*.xmp"):
            dest = target_dir / xmp_file.name
            dest.write_text(xmp_file.read_text(encoding="utf-8"), encoding="utf-8")
            synced += 1
        for retouch_xmp in (repo_presets / "retouch").glob("*.xmp"):
            dest = target_dir / "retouch" / retouch_xmp.name
            dest.write_text(retouch_xmp.read_text(encoding="utf-8"), encoding="utf-8")
            synced += 1
        print(f"[Calotype Bridge] Synced {synced} presets to {target_dir}", flush=True)
    except Exception as e:
        print(f"[Calotype Bridge] Warning while syncing presets: {e}", flush=True)


def kill_process_on_port(port: int):
    """Terminates any stale process holding the port so the bridge can start cleanly."""
    import subprocess
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"],
            capture_output=True, text=True
        )
        pids = [int(p.strip()) for p in res.stdout.strip().split() if p.strip().isdigit()]
        curr_pid = os.getpid()
        for pid in pids:
            if pid != curr_pid and pid > 0:
                print(f"[Calotype Bridge] Freeing port {port}: terminating stale process {pid}...", flush=True)
                subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"])
                time.sleep(0.5)
    except Exception as e:
        print(f"[Calotype Bridge] Note on port check: {e}", flush=True)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0-gpu", "app": "Calotype Local Bridge"}


@app.get("/v1/profiles")
def get_profiles():
    return AVAILABLE_PROFILES


@app.post("/v1/photos")
async def register_photo(request: Request):
    data = await request.json()
    uuid_str = data.get("lr_catalog_uuid")
    if not uuid_str:
        raise HTTPException(status_code=422, detail="Missing lr_catalog_uuid")
    photos_db[uuid_str] = data
    return {"status": "registered", "photo_id": uuid_str}


@app.get("/v1/photos/{uuid_str}")
def get_photo(uuid_str: str):
    if uuid_str not in photos_db:
        raise HTTPException(status_code=404, detail="Unknown photo")
    return photos_db[uuid_str]


def parse_curve_flat(curve_items: list[Any]) -> list[float]:
    """Flattens tone curve items (whether strings 'x, y' or pairs [x, y]) into flat float list."""
    flat = []
    for item in curve_items:
        if isinstance(item, str):
            parts = item.split(",")
            flat.extend([float(parts[0].strip()), float(parts[1].strip())])
        elif isinstance(item, (list, tuple)):
            flat.extend([float(item[0]), float(item[1])])
        elif isinstance(item, (int, float)):
            flat.append(float(item))
    return flat


def process_edit_job_sync(job_id: str, profile_id: str, uuids: list[str]):
    """Processes photos sequentially on local GPU and applies consistency smoothing."""
    import subprocess
    # Find matching profile
    prof = next((p for p in AVAILABLE_PROFILES if p["profile_id"] == profile_id), None)
    preset_key = prof["preset_key"] if prof else "wedding"
    format_type = prof["format_type"] if prof else "raw"

    print(f"\n[Calotype Bridge] Running edit job {job_id} on {len(uuids)} photos with preset '{preset_key}'...", flush=True)

    # 1. Resolve RAW previews if needed
    PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)
    raw_to_extract = []
    file_map: dict[str, Path] = {}
    for u in uuids:
        photo_info = photos_db.get(u, {})
        file_path = photo_info.get("file_path")
        if not file_path:
            continue
        p = Path(file_path)
        if p.suffix.lower() in RAW_EXTS:
            prev = PREVIEW_CACHE / f"{p.stem}.jpg"
            # Also check if existing preview exists next to RAW
            alt_prev = p.parent / f"{p.stem}.jpg"
            alt_prev_dir = Path(r"E:\Marryween_previews") / f"{p.stem}.jpg"
            if prev.exists() and prev.stat().st_size > 0:
                file_map[u] = prev
            elif alt_prev_dir.exists() and alt_prev_dir.stat().st_size > 0:
                file_map[u] = alt_prev_dir
            elif alt_prev.exists() and alt_prev.stat().st_size > 0:
                file_map[u] = alt_prev
            else:
                raw_to_extract.append(str(p))
                file_map[u] = prev
        else:
            file_map[u] = p

    if raw_to_extract and PREVIEW_EXE.exists():
        print(f"[Calotype Bridge] Extracting embedded camera previews for {len(raw_to_extract)} RAW files...", flush=True)
        chunk_size = 50
        for i in range(0, len(raw_to_extract), chunk_size):
            chunk = raw_to_extract[i:i + chunk_size]
            try:
                subprocess.run([str(PREVIEW_EXE), str(PREVIEW_CACHE)] + chunk, capture_output=True, text=True)
            except Exception as e:
                print(f"[Calotype Bridge] Warning during preview extraction: {e}", flush=True)

    engine = get_engine(preset_key)
    raw_results: list[dict[str, Any]] = []

    for idx, u in enumerate(uuids, 1):
        target_path = file_map.get(u)
        if not target_path or not target_path.exists():
            print(f"[Calotype Bridge] Warning: photo {u} path not found: {target_path}", flush=True)
            continue

        try:
            preds = engine.predict(target_path, preset=preset_key)
            
            # Format develop settings specifically for Lightroom SDK
            lr_settings: dict[str, Any] = {
                "ProcessVersion": "15.4",
                "WhiteBalance": "Custom",
                "Exposure2012": float(round(max(-5.0, min(5.0, preds.get("Exposure2012", 0.0))), 2)),
                "Contrast2012": int(round(max(-100, min(100, preds.get("Contrast2012", 0.0))))),
                "Highlights2012": int(round(max(-100, min(100, preds.get("Highlights2012", 0.0))))),
                "Shadows2012": int(round(max(-100, min(100, preds.get("Shadows2012", 0.0))))),
                "Whites2012": int(round(max(-100, min(100, preds.get("Whites2012", 0.0))))),
                "Blacks2012": int(round(max(-100, min(100, preds.get("Blacks2012", 0.0))))),
                "Texture": int(round(preds.get("Texture", 0))),
                "Clarity2012": int(round(preds.get("Clarity2012", 0))),
                "Dehaze": int(round(preds.get("Dehaze", 0))),
                "Vibrance": int(round(preds.get("Vibrance", 0))),
                "Saturation": int(round(preds.get("Saturation", 0))),
            }
            
            if format_type == "jpeg_tiff":
                # In Lightroom, JPEGs use IncrementalTemperature / IncrementalTint
                lr_settings["IncrementalTemperature"] = int(round(preds.get("TemperatureDiff", 0)))
                lr_settings["IncrementalTint"] = int(round(preds.get("TintDiff", 0)))
            else:
                lr_settings["Temperature"] = int(round(preds.get("Temperature", 5500)))
                lr_settings["Tint"] = int(round(preds.get("Tint", 10)))

            # Curves: point curve requires ToneCurveName2012 = "Custom" in Lightroom SDK
            if "ToneCurvePV2012" in preds:
                lr_settings["ToneCurveName2012"] = "Custom"
                lr_settings["ToneCurvePV2012"] = parse_curve_flat(preds["ToneCurvePV2012"])
            for ch in ("Red", "Green", "Blue"):
                key = f"ToneCurvePV2012{ch}"
                if key in preds:
                    lr_settings[key] = parse_curve_flat(preds[key])

            # Copy all HSL / Color Grading / Effects / Detail settings from preds
            for k, v in preds.items():
                if k.startswith(("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")):
                    lr_settings[k] = int(round(v))
                elif k.startswith("ColorGrade"):
                    lr_settings[k] = int(round(v))
                elif k in ("PostCropVignetteAmount", "GrainAmount", "GrainSize", "GrainFrequency"):
                    lr_settings[k] = int(round(v))
                elif k.startswith("Glow"):
                    lr_settings[k] = int(round(v))
                elif k == "ConvertToGrayscale":
                    lr_settings[k] = bool(v)

            raw_results.append({
                "lr_catalog_uuid": u,
                "file_path": file_path,
                "lr_settings": lr_settings,
            })
            if idx % 20 == 0 or idx == len(uuids):
                print(f"  Processed {idx}/{len(uuids)} photos on GPU...", flush=True)
        except Exception as e:
            print(f"[Calotype Bridge] Error on photo {p.name}: {e}", flush=True)

    # Apply consistency smoothing across the batch sequence (anti-flicker)
    n_res = len(raw_results)
    if n_res > 2 and format_type == "raw":
        # Pass 1: 1-frame spikes (Temperature & Exposure)
        for i in range(1, n_res - 1):
            prev_s = raw_results[i-1]["lr_settings"]
            curr_s = raw_results[i]["lr_settings"]
            next_s = raw_results[i+1]["lr_settings"]

            # Temp
            prev_t, curr_t, next_t = prev_s.get("Temperature", 5500), curr_s.get("Temperature", 5500), next_s.get("Temperature", 5500)
            if abs(prev_t - next_t) < 100 and abs(curr_t - prev_t) >= 200:
                curr_s["Temperature"] = int(round((prev_t + next_t) / 2))

            # Exposure
            prev_e, curr_e, next_e = prev_s.get("Exposure2012", 0.0), curr_s.get("Exposure2012", 0.0), next_s.get("Exposure2012", 0.0)
            if abs(prev_e - next_e) < 0.15 and abs(curr_e - prev_e) >= 0.35:
                curr_s["Exposure2012"] = round((prev_e + next_e) / 2, 2)

        # Pass 2: 2-frame wobbles
        for i in range(1, n_res - 2):
            prev_t = raw_results[i-1]["lr_settings"].get("Temperature", 5500)
            c1_t = raw_results[i]["lr_settings"].get("Temperature", 5500)
            c2_t = raw_results[i+1]["lr_settings"].get("Temperature", 5500)
            next_t = raw_results[i+2]["lr_settings"].get("Temperature", 5500)
            if abs(prev_t - next_t) < 120 and abs(c1_t - c2_t) < 80 and abs(c1_t - prev_t) >= 250:
                target_t = int(round((prev_t + next_t) / 2))
                raw_results[i]["lr_settings"]["Temperature"] = target_t
                raw_results[i+1]["lr_settings"]["Temperature"] = target_t

    # Finalize job
    jobs_db[job_id]["results"] = raw_results
    jobs_db[job_id]["status"] = "completed"
    print(f"[Calotype Bridge] Job {job_id} COMPLETED with {len(raw_results)} results!\n", flush=True)


@app.post("/v1/jobs/edit")
async def queue_edit(request: Request):
    data = await request.json()
    profile_id = data.get("profile_id") or "wedding-v6-raw"
    uuids = data.get("lr_catalog_uuids", [])
    if not uuids:
        raise HTTPException(status_code=422, detail="No photos specified")

    job_id = str(uuid.uuid4())
    jobs_db[job_id] = {
        "job_id": job_id,
        "status": "running",
        "results": [],
    }

    # Start processing in background thread
    threading.Thread(
        target=process_edit_job_sync,
        args=(job_id, profile_id, uuids),
        daemon=True,
    ).start()

    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "running"})


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Unknown job")
    return jobs_db[job_id]


@app.get("/v1/automation/next")
def automation_next():
    return Response(status_code=204)


def main():
    parser = argparse.ArgumentParser(description="Calotype Local Bridge Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    kill_process_on_port(args.port)
    ensure_config()
    sync_presets_to_camera_raw()
    print(f"[Calotype Bridge] Starting server on http://{args.host}:{args.port}...")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
