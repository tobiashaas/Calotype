"""Which photos of a selection has the photographer already edited?

Lightroom's develop settings do not say whether a photo was edited: a fresh import carries the
import preset (or the defaults), with the as-shot white balance. So the *most common* state of
the selection's sliders counts as "not edited yet", every photo that differs from it as edited.
This also covers import presets, which give all untouched photos the same values.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from calotype_edit_serializer.sliders import FormatType, _as_float, slider_specs

_AS_SHOT = {None, "", "As Shot", "AsShot", "Wie Aufnahme"}


def keeps_as_shot(settings: Mapping[str, Any], format_type: FormatType) -> bool:
    """RAW photo whose white balance is still the camera's: its Kelvin belongs to this photo
    only, so it must not be copied to other photos. A sidecar without ``WhiteBalance`` but
    with a Kelvin value has its own white balance (Lightroom reads it as custom)."""
    if format_type != "raw":
        return False
    if "WhiteBalance" not in settings:
        return settings.get("Temperature") is None
    return settings["WhiteBalance"] in _AS_SHOT


def edit_signature(settings: Mapping[str, Any], format_type: FormatType) -> tuple:
    """The slider state that tells edited from untouched photos (as-shot Kelvin ignored)."""
    white_balance = settings.get("WhiteBalance")
    as_shot = white_balance in _AS_SHOT
    sig: list = [None if as_shot else white_balance]
    for spec in slider_specs(format_type):
        if as_shot and format_type == "raw" and spec.internal in ("temp", "tint"):
            continue
        value = _as_float(settings.get(spec.lr_key))
        if value is None:
            value = spec.default
        sig.append(None if value is None else round(value, 2))
    return tuple(sig)


def edited_photos(settings: Sequence[Mapping[str, Any]], format_type: FormatType) -> list[bool]:
    """Per photo: edited (differs from the selection's most common state)?

    All False when no state is shared by at least two photos — then there is no baseline to
    tell edits from, and nothing is treated as an example.
    """
    sigs = [edit_signature(s or {}, format_type) for s in settings]
    if not sigs:
        return []
    # Lightroom's defaults win when present: edits synced to many photos can outnumber the
    # untouched ones. Otherwise (import preset) the most common state is the untouched one.
    default = edit_signature({}, format_type)
    counts = Counter(sigs)
    baseline = default if default in counts else counts.most_common(1)[0][0]
    if baseline != default and counts[baseline] < 2:
        return [False] * len(sigs)
    return [s != baseline for s in sigs]


def _same_value(a: Any, b: Any, decimals: int) -> bool:
    x, y = _as_float(a), _as_float(b)
    return x is not None and y is not None and abs(x - y) <= 0.5 * 10 ** -decimals + 1e-9


def unchanged_since(applied: Mapping[str, Any], current: Mapping[str, Any], format_type: FormatType,
                    earlier: Sequence[Mapping[str, Any]] = ()) -> bool:
    """Does a photo still hold the Sliders Calotype applied to it (its result's ``lr_settings``)?

    Compared at Lightroom's precision on the Sliders the result set; keys it did not set (look,
    crop, sliders a profile leaves to the photographer) are ignored. A result without any
    Slider proves nothing, so that is False — as is any Slider the photographer moved since
    (then the photo is a Correction). A RAW photo with its own white balance where the result
    kept the camera's is a Correction too, unless one of the ``earlier`` results (the photo's
    older Calotype results) set exactly that white balance.
    """
    # A result that left the camera's white balance and a photo that no longer has it: the
    # photographer set their own — a Correction, even though no Slider the result set moved —
    # unless an earlier Calotype result (``earlier``) set exactly that white balance.
    wb = [spec for spec in slider_specs(format_type) if spec.internal in ("temp", "tint")]
    if format_type == "raw" and not {s.lr_key for s in wb} & set(applied) and not keeps_as_shot(current, format_type):
        if not any(all(_same_value(e.get(s.lr_key), current.get(s.lr_key), s.decimals) for s in wb)
                   for e in earlier):
            return False
    compared = 0
    for spec in slider_specs(format_type):
        if spec.lr_key not in applied:
            continue
        want = _as_float(applied.get(spec.lr_key))
        have = _as_float(current.get(spec.lr_key))
        if have is None:
            have = spec.default
        if want is None or have is None:
            return False
        if abs(want - have) > 0.5 * 10 ** -spec.decimals + 1e-9:
            return False
        compared += 1
    return compared > 0
