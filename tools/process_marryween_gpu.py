"""GPU-accelerated batch processor for E:\\Marryween DP3A series using Calotype Wedding v6."""

import sys
import time
from pathlib import Path

from calotype_inference_pipeline.npx import (
    DEFAULT_NET_DIR,
    NeurapixInferenceEngine,
    generate_xmp,
)

MARRYWEEN_DIR = Path(r"E:\Marryween")


def main():
    # Deduplicate paths (Windows glob is case-insensitive)
    seen = set()
    jpg_files = []
    for f in sorted(MARRYWEEN_DIR.glob("DP3A*.[jJ][pP][gG]")):
        if f.name.lower() not in seen:
            seen.add(f.name.lower())
            jpg_files.append(f)

    total = len(jpg_files)
    print(f"Found {total} photos in DP3A series in {MARRYWEEN_DIR}", flush=True)
    if total == 0:
        return

    print("Initializing Wedding v6 Neural Engine on GPU...", flush=True)
    t0_load = time.time()
    engine = NeurapixInferenceEngine(net_dir=DEFAULT_NET_DIR, device="cuda")
    print(f"Engine ready on {engine.device} in {time.time()-t0_load:.1f}s", flush=True)

    print(f"Starting GPU batch inference on {total} photos...", flush=True)
    t0 = time.time()
    success = 0

    for idx, jpg in enumerate(jpg_files, 1):
        out_xmp = jpg.with_suffix(".xmp")
        # Skip if already developed with Calotype Wedding in this session
        if out_xmp.exists() and out_xmp.stat().st_size > 500:
            content = out_xmp.read_text(encoding="utf-8", errors="ignore")
            if 'crs:ColorGradeMidtoneHue="68"' in content and "ToneCurvePV2012Blue" in content:
                success += 1
                continue

        try:
            settings = engine.predict(jpg, preset="wedding")
            xmp_str = generate_xmp(settings)
            out_xmp.write_text(xmp_str, encoding="utf-8")
            success += 1
        except Exception as e:
            print(f"[{idx}/{total}] Error on {jpg.name}: {e}", flush=True)

        if idx % 50 == 0 or idx == total:
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = (total - idx) / rate if rate > 0 else 0
            mins, secs = divmod(int(remaining), 60)
            print(f"  [{idx:4d}/{total}] {rate:5.1f} img/s | Elapsed: {elapsed:5.1f}s | ETA: {mins:02d}m{secs:02d}s | Last: {jpg.stem}", flush=True)

    total_time = time.time() - t0
    avg_rate = success / total_time if total_time > 0 else 0
    print(f"\nFinished! Developed and written {success}/{total} XMPs in {total_time:.1f}s ({avg_rate:.2f} img/s).", flush=True)


if __name__ == "__main__":
    main()
