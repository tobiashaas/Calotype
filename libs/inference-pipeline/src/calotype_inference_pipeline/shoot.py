"""Shoot calibration: learn the look of *this* shoot from the photos the photographer already
edited in it.

A profile trained on earlier shoots knows how photos differ from each other, but not the look of
a new shoot (measured on unseen weddings and client jobs: model alone 0-1 % of photos with every
slider within tolerance, the mean of 20 edits of the same shoot 13-64 %). So the edited photos of
the shoot ("references") set the level, and per slider the other photos may deviate from it:

- ``same``:  the value two thirds of the references share — a slider the photographer synced
  over the shoot stays exactly there (measured on the maintainer's own shoot: contrast within
  tolerance 80-86 % with ``blend``, 97 % with this rule; no case of twelve got worse)
- ``mean``:  the references' mean — with fewer than eight references nothing more is learned
- ``blend``: half a ridge regression on the photo's own features (fitted on the references
  only), half the references closest in *content* (the three nearest feature vectors, weighted
  by closeness) — retrieval as in RefRetouch (Weldengus et al. 2026)
- ``blend+scene``: with capture times, a photo taken within two minutes of an edited one takes
  that photo's value (photographers edit one frame of a scene and sync it); the others keep
  ``blend``. Two sliders differ, measured on seven of the maintainer's weddings (previews from
  the archive, 10-50 examples): white balance follows the closest edited photo for ten minutes
  (the light of a scene lasts), and for exposure that photo counts less the further away it is
  — weddings are exposed frame by frame, copying alone was worse there than ``blend``. A fixed rule: choosing by cross-validation whether to follow the closest example,
  or deciding it from how much the examples of a scene agree, both lost. Measured on five
  shoots (three of the maintainer with their catalogs, two edited by other tools; 10-50
  examples, all sliders within tolerance, mean of twelve cases): 36.9 % with the cross-validated
  choice, 39.0 % with this rule — the maintainer's shoots gain (one 25 -> 44 %), a shoot edited
  per photo by another tool loses up to four points

A profile's prediction is one more feature of the photo (after Saeedi et al. 2018: a shared
model, adapted per shoot), like the camera's measurements below. It is *not* a method of its
own: choosing by cross-validation among mean / profile offset / ridge on a handful of examples
was the weak part. On two shoots edited by other tools (internal yardstick; 10 / 20 / 50
examples spread over the shoot; the "profile" trained on the other shoot) all six sliders within
tolerance: the old choice with a profile 15 %, ``blend`` without one 22 %, ``blend`` with the
profile as a feature 22.5 %.

Works on internal parameter names (``exposure``, ``temp`` …); nothing here knows Lightroom.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

# What "right" means per slider (internal units) — the tolerances of the benchmarks.
TOLERANCE = {
    "exposure": 0.15, "temp": 150.0, "tint": 5.0, "contrast": 8.0, "highlights": 8.0,
    "shadows": 8.0, "whites": 8.0, "blacks": 8.0, "vibrance": 5.0, "saturation": 5.0,
}
RIDGE_ALPHA = 50.0
# Below this, cross-validating a regression on the references is noise: only the mean is used.
MIN_FOR_CHOICE = 8
# A photo this close in time to an edited one belongs to its scene.
SCENE_SECONDS = 120.0
# The light of a scene outlasts the single frame: white balance follows the closest edited
# photo for ten minutes.
LIGHT_SCENE_SECONDS = 600.0
LIGHT_SCENE_SLIDERS = ("temp", "tint")
# Exposure is set frame by frame: the closest edited photo counts less the further away it is
# (weight 1/e after this many seconds, the rest is ``blend``), up to ``LIGHT_SCENE_SECONDS``.
EXPOSURE_FADE_SECONDS = 60.0
# References closest in content that set a photo's value in ``blend``.
NEIGHBOURS = 3
# The camera's measured colour temperature joins the features for these sliders, repeated so
# that it carries about a tenth of the weight (153 image features + 16 copies). On the two
# yardstick shoots that lifted temperature within tolerance from 42 to 47 % (mean of six cases,
# none worse); as a fixed offset it failed (a photographer does not follow the camera 1:1).
LIGHT_SLIDERS = ("temp",)
LIGHT_COPIES = 16
# The camera's exposure settings (log2 of ISO, shutter time and f-number, plus the exposure
# compensation) join the features for these sliders the same way: exposure within tolerance
# 49.0 -> 51.7 % (mean of the same six cases, none worse; the kindergarten shoot gains 3-6
# points, the wedding 0.5-2).
CAMERA_SLIDERS = ("exposure",)
CAMERA_COPIES = 8
# A profile's prediction of the slider joins the features of every slider it predicts.
MODEL_COPIES = 8
# Share of the references that must carry the identical value for ``same``.
SHARED_SHARE = 2 / 3


def _ridge(X: np.ndarray, y: np.ndarray):
    """Fitted on the residual to the mean; returns a predictor for new rows."""
    scaler = StandardScaler().fit(X)
    reg = Ridge(alpha=RIDGE_ALPHA).fit(scaler.transform(X), y - y.mean())
    return lambda rows: reg.predict(scaler.transform(rows))


def _similar(X_ref: np.ndarray, truth: np.ndarray, X_new: np.ndarray) -> np.ndarray:
    """Per new photo the mean of its nearest references in feature space, weighted by closeness."""
    scaler = StandardScaler().fit(np.vstack([X_ref, X_new]))
    Z_ref, Z_new = scaler.transform(X_ref), scaler.transform(X_new)
    distance = np.sqrt(((Z_new[:, None, :] - Z_ref[None, :, :]) ** 2).mean(axis=2))
    nearest = np.argsort(distance, axis=1)[:, : min(NEIGHBOURS, len(truth))]
    weight = 1.0 / (np.take_along_axis(distance, nearest, axis=1) + 1e-6)
    return (weight * truth[nearest]).sum(axis=1) / weight.sum(axis=1)


def _shared_value(truth: np.ndarray) -> tuple[float, float]:
    """The most common value among the references and the share of them that carry it."""
    values, counts = np.unique(np.round(truth, 3), return_counts=True)
    most = int(np.argmax(counts))
    return float(values[most]), float(counts[most] / len(truth))


def _scene(slider: str) -> tuple[float, float | None]:
    """How far in time an edited photo reaches for this slider, and over how many seconds its
    weight fades (None: it counts fully up to the limit)."""
    if slider == "exposure":
        return LIGHT_SCENE_SECONDS, EXPOSURE_FADE_SECONDS
    if slider in LIGHT_SCENE_SLIDERS:
        return LIGHT_SCENE_SECONDS, None
    return SCENE_SECONDS, None


def _predict(method: str, truth, X_ref, X_new, t_ref=None, t_new=None, slider: str = "") -> np.ndarray:
    if method == "mean":
        return np.full(len(X_new), float(truth.mean()))
    out = 0.5 * (float(truth.mean()) + _ridge(X_ref, truth)(X_new)) + 0.5 * _similar(X_ref, truth, X_new)
    if method == "blend+scene":
        limit, fade = _scene(slider)
        gaps = np.abs(t_new[:, None] - t_ref[None, :])
        nearest = np.argmin(gaps, axis=1)
        gap = gaps[np.arange(len(t_new)), nearest]
        close = gap <= limit
        weight = np.exp(-gap[close] / fade) if fade else 1.0
        out[close] = weight * truth[nearest[close]] + (1.0 - weight) * out[close]
    return out


def _with_camera(X: np.ndarray, camera: Sequence[Sequence[float]]) -> np.ndarray:
    """The features plus the camera's exposure settings (one row of values per photo), repeated."""
    return np.column_stack([X, np.tile(np.asarray(camera, dtype=float), CAMERA_COPIES)])


def _with_light(X: np.ndarray, kelvin: Sequence[float]) -> np.ndarray:
    """The features plus the camera's measured colour temperature (in 1000 K), repeated."""
    column = np.asarray(kelvin, dtype=float)[:, None] / 1000.0
    return np.column_stack([X, np.tile(column, LIGHT_COPIES)])


def calibrate(
    references: Sequence[Mapping[str, float]],
    reference_model: Sequence[Mapping[str, float]] | None,
    reference_features: Sequence[Sequence[float]],
    model: Sequence[Mapping[str, float]] | None,
    features: Sequence[Sequence[float]],
    reference_times: Sequence[float] | None = None,
    times: Sequence[float] | None = None,
    reference_light: Sequence[float] | None = None,
    light: Sequence[float] | None = None,
    reference_camera: Sequence[Sequence[float]] | None = None,
    camera: Sequence[Sequence[float]] | None = None,
) -> tuple[list[dict[str, float]], dict[str, str]]:
    """Predictions for the other photos of the shoot, and the method chosen per slider.

    references: the photographer's values of the edited photos; reference_model / model: the
    profile's predictions for the edited / the other photos; *_features: their feature vectors.
    Sliders missing from a reference (e.g. RAW temperature without a value) keep the model's
    prediction. reference_times / times: capture times in seconds (both or neither) — photos
    close in time to an edited one take its values (``blend+scene``). reference_model and model None: no profile — the look comes from
    the references alone, and sliders they lack get no value at all. reference_light / light:
    the camera's measured colour temperature in Kelvin per photo (both or neither) — one more
    feature for the sliders in ``LIGHT_SLIDERS``. reference_camera / camera: the camera's
    exposure settings per photo (rows of equal length, both or neither) — more features for the
    sliders in ``CAMERA_SLIDERS``.
    """
    if not references:
        raise ValueError("calibration needs at least one edited photo")
    X_ref = np.asarray(reference_features, dtype=float)
    X_new = np.asarray(features, dtype=float)
    with_times = reference_times is not None and times is not None
    t_ref = np.asarray(reference_times, dtype=float) if with_times else None
    t_new = np.asarray(times, dtype=float) if with_times else None
    with_model = reference_model is not None and model is not None
    with_light = reference_light is not None and light is not None
    if with_light:
        X_ref_light = _with_light(X_ref, reference_light)
        X_new_light = _with_light(X_new, light) if len(X_new) else X_new
    with_camera = reference_camera is not None and camera is not None
    if with_camera:
        X_ref_camera = _with_camera(X_ref, reference_camera)
        X_new_camera = _with_camera(X_new, camera) if len(X_new) else X_new
    out = [dict(m) for m in model] if with_model else [{} for _ in range(len(X_new))]
    methods: dict[str, str] = {}
    params = [p for p in TOLERANCE if all(p in r for r in references)]
    for p in params:
        truth = np.array([r[p] for r in references], dtype=float)
        # A profile may predict only some sliders (one that keeps the camera's white balance
        # has no temperature): the others are calibrated from the references alone.
        modelled = with_model and all(p in m for m in reference_model) and all(p in m for m in model)
        m_ref = np.array([m[p] for m in reference_model], dtype=float) if modelled else None
        m_new = np.array([m[p] for m in model], dtype=float) if modelled else None
        lit = with_light and p in LIGHT_SLIDERS and len(X_new) > 0
        F_ref, F_new = (X_ref_light, X_new_light) if lit else (X_ref, X_new)
        if with_camera and p in CAMERA_SLIDERS and len(X_new) > 0:
            F_ref, F_new = X_ref_camera, X_new_camera
        if modelled and len(X_new) > 0:
            F_ref = np.column_stack([F_ref, np.tile(m_ref[:, None], MODEL_COPIES)])
            F_new = np.column_stack([F_new, np.tile(m_new[:, None], MODEL_COPIES)])
        shared, share = _shared_value(truth)
        if len(truth) >= 3 and share >= SHARED_SHARE:
            methods[p] = "same"
            for row in out:
                row[p] = shared
            continue
        method = "mean" if len(truth) < MIN_FOR_CHOICE else ("blend+scene" if with_times else "blend")
        methods[p] = method
        if not out:
            continue
        for row, value in zip(out, _predict(method, truth, F_ref, F_new, t_ref, t_new, p)):
            row[p] = float(value)
    return out, methods
