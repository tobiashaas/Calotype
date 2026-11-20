"""Calotype Neural Inference Engine.

Runs deep learning PyTorch/TorchScript models on photos, predicts
per-photo exposure, white balance and tone, and merges with the photographer's
base style sliders and signature tone curves.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import zipfile

import numpy as np
from PIL import Image, ImageFilter
import yaml


MODELS_ROOT = Path(os.environ.get("CALOTYPE_MODELS_DIR", r"F:\calotype_models"))
if not MODELS_ROOT.exists():
    fallback = Path(r"F:\decrypted_nets")
    if fallback.exists():
        MODELS_ROOT = fallback

DEFAULT_MODEL_DIR = MODELS_ROOT / "wedding_v6"

PRESET_MODELS = {
    "wedding": MODELS_ROOT / "wedding_v6",
    "wedding-v6": MODELS_ROOT / "wedding_v6",
    "wedding-v4": MODELS_ROOT / "wedding_v4",
    "wedding-herbst-vs": MODELS_ROOT / "wedding_herbst_vs_v2",
    "wedding-herbst": MODELS_ROOT / "wedding_herbst_vs_v2",
    "kita": MODELS_ROOT / "kita_v2",
    "vintage-sunbeam": MODELS_ROOT / "vintage_sunbeam",
    "luminous-dream": MODELS_ROOT / "luminous_dream",
    "eternal-essence": MODELS_ROOT / "eternal_essence",
    "classic-depths-bw": MODELS_ROOT / "classic_depths_bw",
    "gentle-mist-bw": MODELS_ROOT / "gentle_mist_bw",
}

PRESET_BIAS = {
    "wedding": {
        "Texture": 0, "Clarity2012": 10, "Dehaze": 30, "Vibrance": 0, "Saturation": -16,
    },
    "wedding-v6": {
        "Texture": 0, "Clarity2012": 10, "Dehaze": 30, "Vibrance": 0, "Saturation": -16,
    },
    "wedding-v4": {
        "Texture": 0, "Clarity2012": 10, "Dehaze": 30, "Vibrance": 0, "Saturation": -16,
    },
    "wedding-herbst-vs": {
        "Texture": 0, "Clarity2012": 10, "Dehaze": 30, "Vibrance": 0, "Saturation": -16,
    },
    "wedding-herbst": {
        "Texture": 0, "Clarity2012": 10, "Dehaze": 30, "Vibrance": 0, "Saturation": -16,
    },
    "kita": {
        "Texture": 30, "Clarity2012": 10, "Dehaze": 10, "Vibrance": 0, "Saturation": -16,
    },
    "peaky-blinders": {
        "Texture": 15, "Clarity2012": 15, "Dehaze": 62, "Vibrance": -12, "Saturation": -41,
    },
    "vintage-sunbeam": {
        "Texture": -4, "Clarity2012": -3, "Dehaze": 0, "Vibrance": -6, "Saturation": -3,
    },
    "luminous-dream": {
        "Texture": 0, "Clarity2012": 5, "Dehaze": 0, "Vibrance": 1, "Saturation": -25,
    },
    "eternal-essence": {
        "Texture": 0, "Clarity2012": -8, "Dehaze": 0, "Vibrance": -16, "Saturation": 11,
    },
    "classic-depths-bw": {
        "Texture": 11, "Clarity2012": -12, "Dehaze": 4, "Vibrance": 0, "Saturation": 0,
        "ConvertToGrayscale": "True",
    },
    "gentle-mist-bw": {
        "Texture": 11, "Clarity2012": 10, "Dehaze": 0, "Vibrance": 0, "Saturation": 0,
        "ConvertToGrayscale": "True",
    },
}

PRESET_LOOKS = {
    "wedding": {
        "ColorGradeMidtoneHue": 68,
        "ColorGradeMidtoneSat": 13,
        "ColorGradeShadowLum": 0,
        "ColorGradeHighlightLum": 0,
        "ColorGradeGlobalHue": 0,
        "ColorGradeGlobalSat": 0,
        "SaturationAdjustmentGreen": -35,
        "SaturationAdjustmentPurple": -14,
        "SaturationAdjustmentMagenta": -20,
        "SaturationAdjustmentRed": 14,
        "SaturationAdjustmentYellow": 10,
        "ToneCurvePV2012": ["0, 8", "61, 59", "194, 186", "255, 244"],
        "ToneCurvePV2012Blue": ["0, 0", "173, 169", "255, 255"],
    },
    "wedding-herbst-vs": {
        "ColorGradeMidtoneHue": 68,
        "ColorGradeMidtoneSat": 13,
        "ColorGradeShadowLum": 0,
        "ColorGradeHighlightLum": 0,
        "ColorGradeGlobalHue": 0,
        "ColorGradeGlobalSat": 0,
        "SaturationAdjustmentGreen": -35,
        "SaturationAdjustmentPurple": -14,
        "SaturationAdjustmentMagenta": -20,
        "SaturationAdjustmentRed": 14,
        "SaturationAdjustmentYellow": 10,
        "ToneCurvePV2012": ["0, 8", "61, 59", "194, 186", "255, 244"],
        "ToneCurvePV2012Blue": ["0, 0", "173, 169", "255, 255"],
    },
}


class CalotypeNeuralEngine:
    """Loads and runs Calotype deep learning neural preset models."""

    def __init__(
        self,
        model_dir: Path | str | None = None,
        preset: str = "wedding",
        device: str | None = None,
    ):
        import torch
        self.torch = torch
        if model_dir is None:
            preset_key = preset.lower().replace("_", "-")
            self.model_dir = PRESET_MODELS.get(preset_key, DEFAULT_MODEL_DIR)
        else:
            self.model_dir = Path(model_dir)
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        self._models: dict[int, Any] = {}
        self._confs: dict[int, dict[str, Any]] = {}
        self._load_models()

    def _load_models(self) -> None:
        """Loads available TorchScript tokens from model_dir."""
        for tok_idx in range(15):
            tok_path = self.model_dir / f"token{tok_idx:02d}.bin"
            if not tok_path.exists():
                continue
            # Read config
            try:
                with zipfile.ZipFile(tok_path) as z:
                    conf_names = [n for n in z.namelist() if n.endswith("extra/conf")]
                    if conf_names:
                        conf_data = yaml.safe_load(z.read(conf_names[0]))
                        self._confs[tok_idx] = conf_data
            except Exception:
                pass

            # Load TorchScript module
            try:
                model = self.torch.jit.load(str(tok_path), map_location=self.device)
                model.eval()
                self._models[tok_idx] = model
            except Exception as e:
                print(f"[Warning] Failed to load token{tok_idx:02d}.bin: {e}")

    def _get_clamp_and_scale(self, tok_idx: int) -> tuple[float, float, float]:
        conf = self._confs.get(tok_idx, {})
        pred_params = conf.get("predictor", {}).get("params", {})
        ds_params = conf.get("dataset", {}).get("params", {})
        conv_conf = pred_params.get("conversion_conf") or ds_params.get("conversion_conf") or {}
        clamp = conv_conf.get("clamp", {"min": -100.0, "max": 100.0})
        stds = ds_params.get("stds") or [1.0]
        std = float(stds[0]) if isinstance(stds, list) and stds else 1.0
        return float(clamp["min"]), float(clamp["max"]), std

    def predict(
        self,
        image_input: Path | str | Image.Image,
        preset: str = "wedding",
        base_temperature: float = 5500.0,
        base_tint: float = 10.0,
    ) -> dict[str, Any]:
        """Runs inference on an image and returns Lightroom develop settings."""
        import torchvision.transforms as T

        if isinstance(image_input, (str, Path)):
            img = Image.open(image_input)
            try:
                img.draft("RGB", (512, 512))
            except Exception:
                pass
            img = img.convert("RGB")
        else:
            img = image_input.convert("RGB")

        img_240 = img.resize((240, 240), Image.Resampling.LANCZOS)
        blurred_240 = img_240.filter(ImageFilter.GaussianBlur(radius=1.0))

        t3 = T.ToTensor()(img_240).unsqueeze(0).to(self.device)
        t_blur = T.ToTensor()(blurred_240).to(self.device)
        t6 = self.torch.cat([T.ToTensor()(img_240).to(self.device), t_blur], dim=0).unsqueeze(0)

        results: dict[str, Any] = {}

        # 1. Slider models (Tokens 0-7)
        slider_defs = [
            (0, "TemperatureDiff", t6, True),   # Temp offset in K
            (3, "TintDiff", t6, True),          # Tint offset
            (4, "Exposure2012", t3, False),     # Exposure in EV
            (5, "Contrast2012", t3, False),     # Contrast
            (1, "Highlights2012", t3, False),   # Highlights
            (7, "Shadows2012", t3, False),      # Shadows
            (2, "Whites2012", t3, False),       # Whites
            (6, "Blacks2012", t3, False),       # Blacks
        ]

        with self.torch.no_grad():
            for tok_idx, param_name, inp, is_wb in slider_defs:
                if tok_idx not in self._models:
                    continue
                c_min, c_max, std = self._get_clamp_and_scale(tok_idx)
                model = self._models[tok_idx]
                out = model(inp)
                probs = self.torch.softmax(out, dim=-1)
                bin_centers = self.torch.linspace(c_min, c_max, out.shape[-1], device=self.device)
                val = (probs * bin_centers).sum().item()

                if is_wb:
                    results[param_name] = round(val, 1)
                else:
                    scaled = val * std
                    results[param_name] = round(scaled, 2)

        # 2. Pixel expert refinements (Tokens 11-13)
        img_256 = img.resize((256, 256), Image.Resampling.LANCZOS)
        t_256 = T.ToTensor()(img_256).unsqueeze(0).to(self.device)
        seg_dummy = self.torch.zeros(1, 1, 256, 256, device=self.device)

        with self.torch.no_grad():
            if 11 in self._models:
                out_exp, _ = self._models[11](t_256, seg_dummy)
                pxl_exp_bias = out_exp.mean().item() * 0.1
                if "Exposure2012" in results:
                    results["Exposure2012"] = round(results["Exposure2012"] + pxl_exp_bias, 2)

            if 12 in self._models:
                out_tone, _ = self._models[12](t_256, seg_dummy)
                tone_bias = out_tone.mean().item() * 20.0
                if "Highlights2012" in results:
                    results["Highlights2012"] = round(results["Highlights2012"] + tone_bias * -1.5, 1)
                if "Shadows2012" in results:
                    results["Shadows2012"] = round(results["Shadows2012"] + tone_bias * 0.8, 1)

        # 3. White Balance
        temp_diff = results.get("TemperatureDiff", 0.0)
        tint_diff = results.get("TintDiff", 0.0)
        target_temp = max(2000.0, min(50000.0, base_temperature + temp_diff))
        target_tint = max(-150.0, min(150.0, base_tint + tint_diff))

        # 4. Assemble settings
        settings: dict[str, Any] = {
            "ProcessVersion": "15.4",
            "WhiteBalance": "Custom",
            "Temperature": int(round(target_temp)),
            "Tint": int(round(target_tint)),
            "Exposure2012": float(results.get("Exposure2012", 0.0)),
            "Contrast2012": int(round(results.get("Contrast2012", 0.0))),
            "Highlights2012": int(round(results.get("Highlights2012", 0.0))),
            "Shadows2012": int(round(results.get("Shadows2012", 0.0))),
            "Whites2012": int(round(results.get("Whites2012", 0.0))),
            "Blacks2012": int(round(results.get("Blacks2012", 0.0))),
        }

        # 5. Apply style layer (bias sliders + look)
        preset_key = preset.lower().replace("_", "-")
        bias = PRESET_BIAS.get(preset_key, PRESET_BIAS["wedding"])
        look = PRESET_LOOKS.get(preset_key, PRESET_LOOKS["wedding"])
        settings.update(bias)
        settings.update(look)

        return settings


# Alias for backward compatibility
CalotypeInferenceEngine = CalotypeNeuralEngine
NeurapixInferenceEngine = CalotypeNeuralEngine


def generate_xmp(settings: dict[str, Any]) -> str:
    """Generates valid Adobe Camera Raw / Lightroom XMP sidecar XML."""
    lines = [
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>',
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00">',
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">',
        '  <rdf:Description rdf:about=""',
        '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"',
    ]

    for k, v in settings.items():
        if isinstance(v, list):
            continue
        lines.append(f'   crs:{k}="{v}"')

    lines.append('  >')

    for k, v in settings.items():
        if isinstance(v, list):
            lines.append(f'   <crs:{k}>')
            lines.append('    <rdf:Seq>')
            for pt in v:
                lines.append(f'     <rdf:li>{pt}</rdf:li>')
            lines.append('    </rdf:Seq>')
            lines.append(f'   </crs:{k}>')

    lines.extend([
        '  </rdf:Description>',
        ' </rdf:RDF>',
        '</x:xmpmeta>',
        '<?xpacket end="w"?>',
    ])
    return '\n'.join(lines)
