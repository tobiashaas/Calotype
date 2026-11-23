"""Mask strengths: how the photographer sets Lightroom's AI masks (subject, sky, skin …).

An AI mask is semantic: Lightroom finds the subject, sky … on every photo again. So its
correction values transfer to other photos — the strength the photographer gives the subject's
shadows on the edited photos of a shoot is what the other photos of the shoot should get.

The masks are named by our retouch ids (defined once in `tools/presets/build.py`, which writes
`retouch_kinds.py`, the presets and the plugin's list): the plugin adds our mask of that kind
and then sets the learned values on it. Values are Lightroom's local values (-1 … 1 = slider / 100), already multiplied by the correction's amount.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any

# Lightroom's AI mask types → our retouch id, generated from tools/presets/build.py.
from calotype_edit_serializer.retouch_kinds import AI_KINDS

# Local corrections learned per mask (all 0 when untouched). Not: curves, point colors, range
# masks — they are not simple numbers — and LocalCurveRefineSaturation (default 100).
LOCAL_KEYS = (
    "LocalExposure2012", "LocalContrast2012", "LocalHighlights2012", "LocalShadows2012",
    "LocalWhites2012", "LocalBlacks2012", "LocalTexture", "LocalClarity2012", "LocalDehaze",
    "LocalSaturation", "LocalTemperature", "LocalTint", "LocalSharpness", "LocalLuminanceNoise",
)

# Below this a learned value is no adjustment (slider ±0.5).
_MIN_VALUE = 0.005


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _int(v: Any) -> int | None:
    x = _num(v)
    return int(x) if x is not None else None


def _true(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() == "true"
    return bool(v)


def mask_kind(group: Mapping[str, Any]) -> str | None:
    """Our retouch id for one mask correction, or None (brush, gradient, mixed or inverted masks).

    Masks that subtract or intersect (MaskBlendMode ≠ 0) only refine the area and are ignored;
    every adding mask must be an AI mask of the same kind.
    """
    if not isinstance(group, Mapping) or not _true(group.get("CorrectionActive"), True):
        return None
    masks = group.get("CorrectionMasks")
    if not isinstance(masks, Sequence) or isinstance(masks, str):
        return None
    kinds = set()
    for m in masks:
        if not isinstance(m, Mapping) or (_int(m.get("MaskBlendMode")) or 0) != 0:
            continue
        if m.get("What") != "Mask/Image" or _true(m.get("MaskInverted"), False):
            return None
        sub, cat = _int(m.get("MaskSubType")), _int(m.get("MaskSubCategoryID"))
        kind = AI_KINDS.get((sub, cat)) or AI_KINDS.get((sub, None))
        if kind is None:
            return None
        kinds.add(kind)
    return kinds.pop() if len(kinds) == 1 else None


def mask_values(settings: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Per kind of AI mask on one photo: its local values (amount applied). With several
    corrections of one kind, the first counts."""
    groups = settings.get("MaskGroupBasedCorrections") if isinstance(settings, Mapping) else None
    if not isinstance(groups, Sequence) or isinstance(groups, str):
        return {}
    out: dict[str, dict[str, float]] = {}
    for g in groups:
        kind = mask_kind(g)
        if kind is None or kind in out:
            continue
        amount = _num(g.get("CorrectionAmount"))
        amount = 1.0 if amount is None else amount
        out[kind] = {k: v * amount for k in LOCAL_KEYS if (v := _num(g.get(k))) is not None}
    return out


def shared_masks(settings: Sequence[Mapping[str, Any]], min_share: float = 0.5) -> dict[str, dict[str, float]]:
    """The mask strengths the edited photos share: per kind used on at least ``min_share`` of
    them, the median of each local value over the photos with that mask (missing = 0).
    Kinds whose values are all ~0 (a mask without adjustment) are left out."""
    if not settings:
        return {}
    per_photo = [mask_values(s) for s in settings]
    out: dict[str, dict[str, float]] = {}
    kinds = sorted({k for p in per_photo for k in p})
    for kind in kinds:
        rows = [p[kind] for p in per_photo if kind in p]
        if len(rows) < min_share * len(settings):
            continue
        values = {}
        for key in LOCAL_KEYS:
            v = statistics.median(r.get(key, 0.0) for r in rows)
            if abs(v) >= _MIN_VALUE:
                values[key] = round(v, 3)
        if values:
            out[kind] = values
    return out
