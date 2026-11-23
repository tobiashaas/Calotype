"""Look composition: the one place that decides what goes into a photo's develop settings.

Precedence, later wins where they overlap:

1. the predicted sliders (profile and/or shoot calibration), as Lightroom settings;
2. the preset: the profile's base preset adds only its look (``apply_style``); a Look the
   photographer chose for the job replaces it and is used as by hand — its tone sliders too
   (``apply_preset``);
3. the shoot's shared look (what the selection's edited photos share) wins over both: it is
   what this shoot got;
4. straighten crop keys — unless the photo already has a crop or straighten of its own: then
   its own crop stays and the result says so (``kept_crop``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from calotype_edit_serializer.sliders import FormatType, to_lightroom
from calotype_edit_serializer.style import apply_preset, apply_style

# The keys of a crop / straighten in Lightroom's develop settings.
CROP_KEYS = ("CropAngle", "CropLeft", "CropTop", "CropRight", "CropBottom", "HasCrop")


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def has_own_crop(settings: Mapping[str, Any] | None) -> bool:
    """The photo is already cropped or straightened (an angle, or a crop smaller than the
    full frame)."""
    s = settings or {}
    full = (_number(s.get("CropLeft"), 0.0) == 0.0 and _number(s.get("CropTop"), 0.0) == 0.0
            and _number(s.get("CropRight"), 1.0) == 1.0 and _number(s.get("CropBottom"), 1.0) == 1.0)
    return _number(s.get("CropAngle"), 0.0) != 0.0 or not full


@dataclass(frozen=True)
class Composition:
    """A photo's develop settings, and whether its own crop was kept instead of ours."""

    settings: dict[str, Any]
    kept_crop: bool = False


def compose(
    predicted: Mapping[str, float],
    format_type: FormatType,
    *,
    preset: Mapping[str, Any] | None = None,
    chosen_look: bool = False,
    shoot_look: Mapping[str, Any] | None = None,
    crop: Mapping[str, Any] | None = None,
    own_settings: Mapping[str, Any] | None = None,
) -> Composition:
    """Develop settings for one photo (see the module docstring for the precedence).

    predicted: internal slider values; preset: the profile's base preset or, with
    ``chosen_look``, the Look chosen for the job; shoot_look: the look the shoot's edited
    photos share; crop: straighten crop keys (empty / None: no straighten); own_settings: the
    photo's current develop settings (decides whether it keeps its own crop).
    """
    lr = to_lightroom(predicted, format_type)
    settings = apply_preset(lr, preset) if chosen_look else apply_style(lr, preset)
    settings.update(shoot_look or {})
    if not crop:
        return Composition(settings)
    if has_own_crop(own_settings):
        return Composition(settings, kept_crop=True)
    settings.update(crop)
    return Composition(settings)
