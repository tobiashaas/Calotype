"""Style layer: a profile's base preset adds the look on top of the per-photo prediction.

The model predicts what depends on the individual photo (exposure, white balance, tone).
A preset carries what makes the *look*: tone curve, HSL, color grading, texture, grain, glow…
Combining both gives "your exposure and white balance per photo, in this style".

Precedence:
- photo-dependent sliders (exposure, white balance, contrast and the four tone sliders)
  always come from the model — a preset made on another photo cannot know them;
- look sliders come from the preset when it sets them (vibrance and saturation included);
- anything else in a preset (crop, masks, lens profiles, camera-specific settings) is
  ignored: it belongs to the photo the preset was made on.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

# Never taken from a preset: these depend on the individual photo.
PHOTO_DEPENDENT = frozenset({
    "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
    "Temperature", "Tint", "IncrementalTemperature", "IncrementalTint", "WhiteBalance",
})

_STYLE_PREFIXES = (
    "ToneCurve", "Parametric", "HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment",
    "ColorGrade", "SplitToning", "GrainAmount", "GrainSize", "GrainFrequency",
    "PostCropVignette", "Glow",   # Glow*: Lightroom 16 (Nov 2026), effect "Glow"
)
_STYLE_KEYS = frozenset({
    "Texture", "Clarity2012", "Dehaze", "Vibrance", "Saturation", "ConvertToGrayscale",
    "CameraProfile", "Sharpness", "SharpenRadius", "SharpenDetail", "SharpenEdgeMasking",
    "LuminanceSmoothing", "ColorNoiseReduction",
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


def shared_style(settings: Sequence[Mapping[str, Any]], min_share: float = 0.5) -> dict[str, Any]:
    """The look the photographer gave a whole shoot: per look setting, the value most of the
    edited photos share (at least ``min_share`` of them, and no tie).

    Vibrance and saturation are left out — they are predicted per photo. Settings missing
    from a photo count as a value of their own, so a look used on few photos is not spread.
    """
    looks = [style_settings(s) for s in settings]
    if not looks:
        return {}
    out: dict[str, Any] = {}
    for key in sorted({k for look in looks for k in look} - _PREDICTED):
        counts = Counter(_hashable(look.get(key)) for look in looks)
        (value, n), *rest = counts.most_common(2) + [(None, 0)]
        if value is not None and n >= min_share * len(looks) and n > rest[0][1]:
            out[key] = next(look[key] for look in looks if _hashable(look.get(key)) == value)
    return out


_PREDICTED = frozenset({"Vibrance", "Saturation"})


def _hashable(v: Any) -> Any:
    return tuple(v) if isinstance(v, list) else v


def apply_style(predicted: Mapping[str, Any], preset: Mapping[str, Any] | None) -> dict[str, Any]:
    """Prediction + look. Photo-dependent sliders stay predicted, the look comes from the preset."""
    merged = dict(predicted)
    merged.update(style_settings(preset))
    for k in PHOTO_DEPENDENT:
        if k in predicted:
            merged[k] = predicted[k]
    return merged


# Tone sliders: many presets carry their whole look in them (strong contrast, pulled highlights).
TONE_SLIDERS = ("Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012")
# The white balance a preset with a fixed Kelvin value is assumed to be made for (daylight).
NEUTRAL_KELVIN = 5500.0


def apply_preset(predicted: Mapping[str, Any], preset: Mapping[str, Any] | None) -> dict[str, Any]:
    """A preset the photographer chose for the job, used as by hand: the look *and* the tone
    sliders come from the preset; exposure and white balance stay per photo.

    A preset with a fixed Kelvin value (``WhiteBalance`` "Custom") is warmer or cooler than
    daylight; the predicted Kelvin is shifted by that much (in mired, as Lightroom's slider is
    perceptually even there), so a warm preset stays warm without one Kelvin value for every
    light. Tint stays predicted — a preset's absolute tint says nothing about the camera's.
    """
    merged = apply_style(predicted, preset)
    if not preset:
        return merged
    for k in TONE_SLIDERS:
        v = preset.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            merged[k] = v
    kelvin, temp = preset.get("Temperature"), predicted.get("Temperature")
    if (preset.get("WhiteBalance") == "Custom" and isinstance(kelvin, (int, float)) and kelvin > 0
            and isinstance(temp, (int, float)) and temp > 0):
        mired = 1e6 / temp - (1e6 / NEUTRAL_KELVIN - 1e6 / kelvin)
        merged["Temperature"] = round(min(50000.0, max(2000.0, 1e6 / max(mired, 20.0))))
    return merged
