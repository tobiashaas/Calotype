"""Neurapix SmartPreset standalone inference CLI for Calotype.

Runs the decrypted PyTorch/TorchScript models (Wedding v6 etc.) on photos,
predicts per-image exposure, white balance, tone values and merges them with
the photographer's base style sliders and tone curves.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from calotype_inference_pipeline.npx import (
    DEFAULT_NET_DIR,
    NeurapixInferenceEngine,
    generate_xmp,
)


def main():
    parser = argparse.ArgumentParser(description="Calotype Neurapix Model Inference")
    parser.add_argument("input", help="Image path or folder of images")
    parser.add_argument("--preset", default="wedding", help="Preset name (wedding, wedding-herbst-vs, kita, peaky-blinders)")
    parser.add_argument("--net-dir", default=str(DEFAULT_NET_DIR), help="Path to decrypted nets")
    parser.add_argument("--out-xmp", action="store_true", help="Write .xmp sidecars next to photos")
    parser.add_argument("--base-temp", type=float, default=5500.0, help="Camera as-shot temperature")
    parser.add_argument("--base-tint", type=float, default=10.0, help="Camera as-shot tint")
    args = parser.parse_args()

    engine = NeurapixInferenceEngine(net_dir=args.net_dir)
    p = Path(args.input)

    files = [p] if p.is_file() else sorted(list(p.glob("*.jpg")) + list(p.glob("*.CR2")) + list(p.glob("*.CR3")) + list(p.glob("*.ARW")) + list(p.glob("*.RAF")))
    if not files:
        print(f"No matching files found in {p}")
        return

    print(f"Processing {len(files)} file(s) with {args.preset} model...")
    for f in files:
        res = engine.predict(f, preset=args.preset, base_temperature=args.base_temp, base_tint=args.base_tint)
        print(f"\n--- {f.name} ---")
        for k in ["Exposure2012", "Temperature", "Tint", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012"]:
            print(f"  {k:16s}: {res.get(k)}")
        print(f"  Bias sliders    : Texture={res.get('Texture')}, Clarity={res.get('Clarity2012')}, Dehaze={res.get('Dehaze')}, Saturation={res.get('Saturation')}")

        if args.out_xmp:
            xmp_content = generate_xmp(res)
            out_file = f.with_suffix(".xmp")
            out_file.write_text(xmp_content, encoding="utf-8")
            print(f"  -> Written to {out_file}")


if __name__ == "__main__":
    main()
