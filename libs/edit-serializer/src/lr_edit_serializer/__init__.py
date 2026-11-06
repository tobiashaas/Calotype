"""Translate between internal model parameters and Lightroom Classic develop settings."""

from collections.abc import Mapping

from lr_edit_serializer.sliders import (
    FormatType,
    SliderSpec,
    from_lightroom,
    slider_specs,
    to_lightroom,
)

__all__ = [
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
