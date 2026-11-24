"""Edit plan: what every photo of an edit job gets — the edit job's domain logic in one place.

``plan_edit(request, profile, photos)`` takes the photos of a selection as they are (settings,
feature vector, EXIF snapshot, analysis) and returns one result per photo to edit. The worker
loads and saves around it; the eval tools call it directly, so the yardstick measures the
production pipeline. No queue, database or object store here (ADR-003): this module imports
only the domain libraries.

Order, later steps building on earlier ones:

1. the profile's prediction per photo (none without a profile); a RAW photo still on the
   camera's white balance passes its as-shot Kelvin, so it can keep it;
2. with ``learn_from_edits``: the selection's edited photos become examples (no result for
   them) and the others are calibrated to the shoot (``shoot.calibrate``); without a profile
   the examples are the only source of the look — none is an error (``NoExamplesError``);
3. with ``consistent_series``: exposure and white balance of a series are pulled together,
   the examples fixed;
4. the look (``compose``): preset → the shoot's shared look → straighten crop, a photo with its
   own crop keeping it;
5. mask strengths: the profile's, or — with examples — the ones the examples share.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from calotype_domain.failures import FailureCode, JobFailure
from calotype_edit_serializer import (
    compose,
    edited_photos,
    from_lightroom,
    keeps_as_shot,
    shared_masks,
    shared_style,
)
from calotype_inference_pipeline import run_inference
from calotype_inference_pipeline.exif import ExifSnapshot, _number  # noqa: F401  (ExifSnapshot re-exported)
from calotype_inference_pipeline.series import smooth
from calotype_inference_pipeline.shoot import calibrate
from calotype_inference_pipeline.straighten import MIN_LINES, crop_settings

# A prediction: (feature vector, the photo's as-shot Kelvin or None) → internal slider values.
Predict = Callable[..., dict[str, float]]  # (vector, as_shot_temp, capture_time=None) -> sliders


class NoExamplesError(JobFailure, ValueError):
    """Without a profile, the selection holds no edited photo to learn the look from."""

    code = FailureCode.NO_EXAMPLES

    def __init__(self) -> None:
        super().__init__("no edited photos in the selection to learn the look from")


@dataclass(frozen=True)
class ShootPhoto:
    """One photo of the selection: its develop settings, feature vector (in the profile's
    feature version; None = no usable preview, so neither example nor target), EXIF snapshot
    and analysis (``straighten``, ``preview_size``)."""

    photo_id: Hashable
    settings: Mapping[str, Any]
    vector: Sequence[float] | None
    exif: ExifSnapshot = ExifSnapshot()
    analysis: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class EditProfile:
    """What the job edits with: a profile (prediction, base preset, mask strengths) or — with
    ``predict`` None — only the selection's edited photos."""

    format_type: str
    predict: Predict | None = None
    base_preset: Mapping[str, Any] = field(default_factory=dict)
    retouch: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, model_bytes: bytes, format_type: str, base_preset: Mapping[str, Any] | None = None,
                   retouch: Mapping[str, Any] | None = None) -> EditProfile:
        def predict(vector: Sequence[float], as_shot_temp: float | None,
                    capture_time: float | None = None) -> dict[str, float]:
            return run_inference(model_bytes, list(vector), as_shot_temp=as_shot_temp, capture_time=capture_time)

        return cls(format_type, predict, dict(base_preset or {}), dict(retouch or {}))


@dataclass(frozen=True)
class EditRequest:
    """The options of an edit job (``job-edit-request-v1``)."""

    learn_from_edits: bool = False
    consistent_series: bool = False
    straighten: bool = False
    look: Mapping[str, Any] | None = None   # a Look chosen for the job: replaces the profile's

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> EditRequest:
        chosen = payload.get("base_preset")
        return cls(
            learn_from_edits=bool(payload.get("learn_from_edits")),
            consistent_series=bool(payload.get("consistent_series")),
            straighten=bool(payload.get("straighten")),
            look=dict(chosen) if isinstance(chosen, dict) and chosen else None,
        )


@dataclass(frozen=True)
class PhotoResult:
    photo_id: Hashable
    lr_settings: dict[str, Any]
    retouch: dict[str, Any] | None = None   # mask strengths to add, None when none learned
    kept_crop: bool = False                  # straightened, but the photo's own crop stays


@dataclass(frozen=True)
class EditPlan:
    results: list[PhotoResult]
    notes: list[str] = field(default_factory=list)   # what was decided, for the job's log


def straighten_settings(analysis: Mapping[str, Any] | None) -> dict:
    """Lightroom crop keys that level the photo — only with clear reference lines, else none."""
    tilt = (analysis or {}).get("straighten") or {}
    size = (analysis or {}).get("preview_size") or []
    angle = float(tilt.get("crop_angle") or 0.0)
    if not angle or int(tilt.get("lines") or 0) < MIN_LINES or len(size) != 2:
        return {}
    # Lightroom's crop corners refer to the sensor image; sensors are landscape, the preview
    # may be upright portrait — only the aspect ratio matters.
    return crop_settings(angle, max(size), min(size))


def _example_values(photo: ShootPhoto, format_type: str) -> dict[str, float]:
    """An edited photo's sliders as an example. Still on the camera's white balance: its
    Kelvin belongs to that photo only — nothing the photographer chose to pass on."""
    values = from_lightroom(photo.settings, format_type)
    if keeps_as_shot(photo.settings, format_type):
        values.pop("temp", None)
        values.pop("tint", None)
    return values


def _all_or_none(photos: Sequence[ShootPhoto], value: Callable[[ShootPhoto], Any]) -> list | None:
    """A feature for every photo, or None as soon as one lacks it."""
    values = [value(p) for p in photos]
    return None if any(v is None for v in values) else values


def _calibrate(predictions: dict, usable: list[ShootPhoto], photos: Sequence[ShootPhoto],
               profile: EditProfile, notes: list[str]) -> list[ShootPhoto]:
    """Learn the shoot's look from the edited photos; rewrites the others' predictions and
    returns them (the targets)."""
    fmt = profile.format_type
    with_model = profile.predict is not None
    edited = dict(zip([p.photo_id for p in photos], edited_photos([p.settings for p in photos], fmt)))
    refs = [p for p in usable if edited[p.photo_id]]
    rest = [p for p in usable if not edited[p.photo_id]]
    if not with_model and not refs:
        raise NoExamplesError()
    if not refs or not rest:
        notes.append(f"no shoot calibration (examples={len(refs)}, to edit={len(rest)})")
        return usable
    references = [_example_values(p, fmt) if not with_model else from_lightroom(p.settings, fmt)
                  for p in refs]
    times = _all_or_none(refs + rest, lambda p: p.exif.capture_time)
    light = _all_or_none(refs + rest, lambda p: p.exif.measured_kelvin)
    camera = _all_or_none(refs + rest, lambda p: p.exif.camera_exposure)
    n = len(refs)
    calibrated, methods = calibrate(
        references,
        [predictions[p.photo_id] for p in refs] if with_model else None,
        [p.vector for p in refs],
        [predictions[p.photo_id] for p in rest] if with_model else None,
        [p.vector for p in rest],
        times[:n] if times else None, times[n:] if times else None,
        light[:n] if light else None, light[n:] if light else None,
        camera[:n] if camera else None, camera[n:] if camera else None,
    )
    for p, values in zip(rest, calibrated):
        predictions[p.photo_id] = values
    notes.append(f"shoot calibration from {len(refs)} edited photos, {len(rest)} to edit, capture times "
                 f"{times is not None}, camera light {light is not None}, camera exposure "
                 f"{camera is not None}, methods {methods}")
    return rest


def _smooth_series(predictions: dict, usable: list[ShootPhoto], targets: list[ShootPhoto],
                   format_type: str, notes: list[str]) -> None:
    """Pull exposure and white balance of each series together (the targets' predictions);
    the other usable photos are the photographer's examples: fixed, they anchor their series."""
    times = _all_or_none(usable, lambda p: p.exif.capture_time)
    if len(usable) < 2 or times is None:
        notes.append(f"no series consistency (photos={len(usable)}, capture times missing)")
        return
    wanted = {p.photo_id for p in targets}
    values = [predictions[p.photo_id] if p.photo_id in wanted else _example_values(p, format_type)
              for p in usable]
    smoothed = smooth(values, [p.vector for p in usable], times, [p.photo_id not in wanted for p in usable])
    for p, row in zip(usable, smoothed):
        if p.photo_id in wanted:
            predictions[p.photo_id] = row
    notes.append(f"series consistency over {len(usable)} photos ({len(usable) - len(wanted)} fixed examples)")


def plan_edit(request: EditRequest, profile: EditProfile, photos: Sequence[ShootPhoto]) -> EditPlan:
    """The develop settings (and mask strengths) for every photo of the selection to edit.

    Photos without a feature vector get no result. Raises ``NoExamplesError`` when there is
    no profile and no edited photo to learn from.
    """
    fmt = profile.format_type
    notes: list[str] = []
    usable = [p for p in photos if p.vector is not None]
    predictions: dict[Hashable, dict[str, float]] = {}
    for p in usable:
        # The camera's Kelvin of a photo still on it decides whether it keeps it.
        as_shot = _number(p.settings.get("Temperature")) if keeps_as_shot(p.settings, fmt) else None
        # Its capture time tells whether the profile saw the photographer correct this light.
        predictions[p.photo_id] = (profile.predict(p.vector, as_shot, p.exif.capture_time)
                                   if profile.predict else {})

    targets = usable
    shoot_look: dict[str, Any] = {}
    retouch = dict(profile.retouch)
    if request.learn_from_edits:
        targets = _calibrate(predictions, usable, photos, profile, notes)
        wanted = {p.photo_id for p in targets}
        examples = [p for p in usable if p.photo_id not in wanted]
        # The shoot's own look wins over the profile's preset: it is what this shoot got.
        shoot_look = shared_style([p.settings for p in examples])
        notes.append(f"shoot look from the edited photos: {len(shoot_look)} settings "
                     f"({', '.join(sorted(k for k in shoot_look if shoot_look[k]))[:300]})")
        # Same for the masks: with examples, their mask setup replaces the profile's (a shoot
        # without sky masks in its examples gets none from the profile either).
        if examples:
            retouch = shared_masks([p.settings for p in examples])
            notes.append(f"mask strengths from the edited photos: {retouch}")

    if request.consistent_series:
        _smooth_series(predictions, usable, targets, fmt, notes)

    preset = request.look if request.look is not None else profile.base_preset
    results = []
    for p in targets:
        composed = compose(
            predictions[p.photo_id], fmt,
            preset=preset, chosen_look=request.look is not None, shoot_look=shoot_look,
            crop=straighten_settings(p.analysis) if request.straighten else None,
            own_settings=p.settings,
        )
        settings = composed.settings
        # The profile kept the camera's white balance: say so. Leaving the keys out would leave
        # whatever Kelvin an earlier run (or another profile) put on the photo.
        if (fmt == "raw" and profile.predict is not None
                and not {"Temperature", "Tint", "WhiteBalance"} & set(settings)):
            settings = {**settings, "WhiteBalance": "As Shot"}
        results.append(PhotoResult(p.photo_id, settings, retouch or None, composed.kept_crop))
    return EditPlan(results, notes)
