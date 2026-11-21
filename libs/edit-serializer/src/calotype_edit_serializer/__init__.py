"""Translate between internal model parameters and Lightroom Classic develop settings."""

from collections.abc import Mapping

from calotype_edit_serializer.edits import edit_signature, edited_photos, keeps_as_shot
from calotype_edit_serializer.masks import mask_values, shared_masks
from calotype_edit_serializer.style import PHOTO_DEPENDENT, apply_preset, apply_style, is_style_key, shared_style, style_settings
from calotype_edit_serializer.sliders import (
    FormatType,
    SliderSpec,
    from_lightroom,
    slider_specs,
    to_lightroom,
)

__all__ = [
    "PHOTO_DEPENDENT",
    "apply_preset",
    "apply_style",
    "edit_signature",
    "edited_photos",
    "keeps_as_shot",
    "mask_values",
    "shared_masks",
    "is_style_key",
    "shared_style",
    "style_settings",
    "FormatType",
    "SliderSpec",
    "from_lightroom",
    "serialize_for_lightroom",
    "slider_specs",
    "to_lightroom",
    "ping",
]


def serialize_for_lightroom(
    edit: Mapping[str, float], format_type: FormatType = "raw"
) -> dict[str, float]:
    """Model prediction → settings ready for ``photo:applyDevelopSettings()``."""
    return to_lightroom(edit, format_type)


def ping() -> str:
    return "edit-serializer"
