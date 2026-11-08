"""Mapping between internal model parameters and Lightroom Classic develop settings.

Internal names (``exposure``, ``temp`` …) are what the model trains on and predicts.
Lightroom names (``Exposure2012``, ``Temperature`` …) are what ``photo:getDevelopSettings()``
returns and ``photo:applyDevelopSettings()`` accepts (Process Version 2012 and later).

White balance differs by file type: RAW files use absolute Kelvin (``Temperature``/``Tint``),
JPEG/TIFF files use relative sliders (``IncrementalTemperature``/``IncrementalTint``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

FormatType = Literal["raw", "jpeg_tiff"]


@dataclass(frozen=True)
class SliderSpec:
    internal: str
    lr_key: str
    minimum: float
    maximum: float
    decimals: int  # Lightroom's slider precision
    default: float | None  # value when Lightroom omits the key; None = no safe default


_COMMON: tuple[SliderSpec, ...] = (
    SliderSpec("exposure", "Exposure2012", -5.0, 5.0, 2, 0.0),
    SliderSpec("contrast", "Contrast2012", -100.0, 100.0, 0, 0.0),
    SliderSpec("highlights", "Highlights2012", -100.0, 100.0, 0, 0.0),
    SliderSpec("shadows", "Shadows2012", -100.0, 100.0, 0, 0.0),
    SliderSpec("whites", "Whites2012", -100.0, 100.0, 0, 0.0),
    SliderSpec("blacks", "Blacks2012", -100.0, 100.0, 0, 0.0),
    SliderSpec("vibrance", "Vibrance", -100.0, 100.0, 0, 0.0),
    SliderSpec("saturation", "Saturation", -100.0, 100.0, 0, 0.0),
)

_WHITE_BALANCE: dict[str, tuple[SliderSpec, ...]] = {
    # As-shot Kelvin differs per photo, so a missing RAW temperature has no safe default.
    "raw": (
        SliderSpec("temp", "Temperature", 2000.0, 50000.0, 0, None),
        SliderSpec("tint", "Tint", -150.0, 150.0, 0, 0.0),
    ),
    "jpeg_tiff": (
        SliderSpec("temp", "IncrementalTemperature", -100.0, 100.0, 0, 0.0),
        SliderSpec("tint", "IncrementalTint", -100.0, 100.0, 0, 0.0),
    ),
}


def slider_specs(format_type: FormatType) -> tuple[SliderSpec, ...]:
    if format_type not in _WHITE_BALANCE:
        raise ValueError(f"unknown format_type {format_type!r} (expected 'raw' or 'jpeg_tiff')")
    return _WHITE_BALANCE[format_type] + _COMMON


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def from_lightroom(settings: Mapping[str, Any], format_type: FormatType) -> dict[str, float]:
    """Lightroom develop settings → internal parameters (training targets).

    Keys Lightroom omitted fall back to the slider's neutral default. Sliders without a
    safe default (RAW temperature) are left out, so callers can detect incomplete rows.
    """
    result: dict[str, float] = {}
    for spec in slider_specs(format_type):
        value = _as_float(settings.get(spec.lr_key))
        if value is None:
            value = spec.default
        if value is not None:
            result[spec.internal] = value
    return result


def to_lightroom(params: Mapping[str, float], format_type: FormatType) -> dict[str, float]:
    """Internal parameters (model predictions) → Lightroom develop settings.

    Values are clamped to Lightroom's slider range and rounded to its precision.
    Unknown or non-numeric parameters are dropped; nothing is invented for missing ones.
    """
    result: dict[str, float] = {}
    for spec in slider_specs(format_type):
        value = _as_float(params.get(spec.internal))
        if value is None:
            continue
        clamped = min(max(value, spec.minimum), spec.maximum)
        result[spec.lr_key] = round(clamped, spec.decimals) if spec.decimals else float(round(clamped))
    return result
