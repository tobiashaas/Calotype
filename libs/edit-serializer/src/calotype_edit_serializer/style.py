"""Style layer: a profile's base preset adds the look on top of the per-photo prediction.

The model predicts what depends on the individual photo (exposure, white balance, tone).
A preset carries what makes the *look*: tone curve, HSL, color grading, texture, grain…
Combining both gives "your exposure and white balance per photo, in this style".

Precedence:
- photo-dependent sliders (exposure, white balance, contrast and the four tone sliders)
  always come from the model — a preset made on another photo cannot know them;
- look sliders come from the preset when it sets them (vibrance and saturation included);
- anything else in a preset (crop, masks, lens profiles, camera-specific settings) is
  ignored: it belongs to the photo the preset was made on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Never taken from a preset: these depend on the individual photo.
PHOTO_DEPENDENT = frozenset({
    "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
    "Temperature", "Tint", "IncrementalTemperature", "IncrementalTint", "WhiteBalance",
})

_STYLE_PREFIXES = (
    "ToneCurve", "Parametric", "HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment",
    "ColorGrade", "SplitToning", "GrainAmount", "GrainSize", "GrainFrequency",
    "PostCropVignette",
)
_STYLE_KEYS = frozenset({
    "Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation", "ConvertToGrayscale",
    "CameraProfile", "Sharpness", "LuminanceSmoothing", "ColorNoiseReduction",
    "GrayMixerRed", "GrayMixerOrange", "GrayMixerYellow", "GrayMixerGreen",
    "GrayMixerAqua", "GrayMixerBlue", "GrayMixerPurple", "GrayMixerMagenta",
})


def is_style_key(key: str) -> bool:
    if key in PHOTO_DEPENDENT:
        return False
    return key in _STYLE_KEYS or key.startswith(_STYLE_PREFIXES)


def style_settings(preset: Mapping[str, Any] | None) -> dict[str, Any]:
    """The look part of a preset (see module docstring), ready to merge."""
    if not preset:
        return {}
    out: dict[str, Any] = {}
    for k, v in preset.items():
        if not is_style_key(k) or v is None:
            continue
        if isinstance(v, bool) or isinstance(v, (int, float, str)):
            out[k] = v
        elif isinstance(v, (list, tuple)) and k.startswith("ToneCurve") and all(
            isinstance(x, (int, float)) for x in v
        ) and len(v) % 2 == 0:
            out[k] = [float(x) for x in v]  # flat point list x0, y0, x1, y1 … (0–255)
    return out


def apply_style(predicted: Mapping[str, Any], preset: Mapping[str, Any] | None) -> dict[str, Any]:
    """Prediction + look. Photo-dependent sliders stay predicted, the look comes from the preset."""
    merged = dict(predicted)
    merged.update(style_settings(preset))
    for k in PHOTO_DEPENDENT:
        if k in predicted:
            merged[k] = predicted[k]
    return merged
