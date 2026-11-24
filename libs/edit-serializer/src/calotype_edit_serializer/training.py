"""What a training photo teaches: the sliders the photographer decided, and whether the photo
kept the camera's white balance.

Not every value in a photo's settings is a decision. A preset applied on import leaves its
values on every photo the photographer did not touch — on one wedding the highlights stood at
the preset's -100 on half the photos, while the photographer set them between -60 and +20
where they cared. Training on those placeholders teaches the preset, not the photographer.
``untouched`` names such values (Lightroom key → value); a slider holding one is left out of
that photo's target, the photo still teaches every other slider.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from calotype_edit_serializer.edits import keeps_as_shot
from calotype_edit_serializer.sliders import FormatType, _as_float, from_lightroom, slider_specs


@dataclass(frozen=True)
class TrainingTarget:
    sliders: dict[str, float]  # internal name → value, only the sliders the photographer decided
    as_shot: bool  # kept the camera's white balance; its Kelvin (if known) is still in sliders


def training_target(
    settings: Mapping[str, Any], format_type: FormatType, untouched: Mapping[str, Any] | None = None,
) -> TrainingTarget:
    sliders = from_lightroom(settings, format_type)
    for spec in slider_specs(format_type):
        placeholder = _as_float((untouched or {}).get(spec.lr_key))
        value = sliders.get(spec.internal)
        if placeholder is not None and value is not None and abs(value - placeholder) < 1e-6:
            del sliders[spec.internal]
    return TrainingTarget(sliders=sliders, as_shot=keeps_as_shot(settings, format_type))
