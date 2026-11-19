"""Batch processor for E:\\Marryween using Calotype Wedding v6 neural model."""

import subprocess
import sys
import time
from pathlib import Path
from PIL import Image

from calotype_inference_pipeline.npx import (
    DEFAULT_NET_DIR,
    NeurapixInferenceEngine,
    generate_xmp,
)

RAW_DIR = Path(r"E:\Marryween")
PREVIEW_DIR = Path(r"E:\Marryween_previews")
PREVIEW_EXE = Path(r"C:\Github\LR-FrameFlow\apps\bridge\target\release\examples\preview.exe")


def main():
    raw_files = sorted(list(RAW_DIR.glob("*.CR2")) + list(RAW_DIR.glob("*.cr2")))
    total = len(raw_files)
    print(f"Found {total} RAW files in {RAW_DIR}")
    if total == 0:
        return

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Check which previews need extraction
    missing_previews = []
    for raw in raw_files:
        prev = PREVIEW_DIR / f"{raw.stem}.jpg"
        if not prev.exists() or prev.stat().st_size == 0:
            missing_previews.append(str(raw))

    if missing_previews:
        print(f"Extracting camera previews for {len(missing_previews)} RAW files via preview.exe...")
        t0 = time.time()
        # Batch in chunks of 50 to avoid cmdline limits
        chunk_size = 50
        for i in range(0, len(missing_previews), chunk_size):
            chunk = missing_previews[i:i + chunk_size]
            cmd = [str(PREVIEW_EXE), str(PREVIEW_DIR)] + chunk
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[Warning] preview.exe error on chunk {i}: {res.stderr[:200]}")
            print(f"  Extracted {min(i + chunk_size, len(missing_previews))}/{len(missing_previews)}...")
        print(f"Preview extraction completed in {time.time() - t0:.1f}s.")
    else:
        print("All camera previews already extracted.")

    # 2. Run inference
    print("\nLoading Wedding v6 neural engine...")
    t0_infer = time.time()
    engine = NeurapixInferenceEngine(net_dir=DEFAULT_NET_DIR)

    print(f"Running neural inference on {total} photos...")
    success = 0
    for idx, raw in enumerate(raw_files, 1):
        prev_path = PREVIEW_DIR / f"{raw.stem}.jpg"
        if not prev_path.exists():
            print(f"[{idx}/{total}] Skipping {raw.name} (no preview)")
            continue

        settings = engine.predict(prev_path, preset="wedding")
        xmp_str = generate_xmp(settings)

        out_xmp = raw.with_suffix(".xmp")
        out_xmp.write_text(xmp_str, encoding="utf-8")
        success += 1

        if idx % 20 == 0 or idx == total:
            elapsed = time.time() - t0_infer
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"  [{idx}/{total}] processed ({rate:.1f} photos/sec) -> {out_xmp.name}")

    total_time = time.time() - t0_infer
    print(f"\nDone! Successfully developed and created {success}/{total} XMPs in {total_time:.1f}s ({success/total_time:.1f} img/s).")


if __name__ == "__main__":
    main()
