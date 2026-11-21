"""Shoot calibration: learn the look of *this* shoot from the photos the photographer already
edited in it.

A profile trained on earlier shoots knows how photos differ from each other, but not the look of
a new shoot (measured on unseen weddings and client jobs: model alone 0-1 % of photos with every
slider within tolerance, the mean of 20 edits of the same shoot 13-64 %). So the edited photos of
the shoot ("references") set the level, and per slider a small cross-validation on them picks how
the other photos may deviate from it:

- ``mean``:  the references' mean — a constant look (studio, uniform light)
- ``model``: mean + beta * (profile prediction - its mean on the references), beta in [0, 1]
- ``ridge``: mean + ridge regression on the photo's own features, fitted on the references only
- ``series``: the value of the reference taken closest in time (same scene, same light) — only
  when capture times are known
- ``blend``: half ``ridge``, half the references closest in *content* (the three nearest feature
  vectors, weighted by closeness) — retrieval as in RefRetouch (Weldengus et al. 2026)

Without a profile the choice is only between ``blend`` and ``series``: on two shoots edited by
other tools (internal yardstick, 10 / 20 / 50 examples spread over the shoot) ``blend`` alone put
19 % of the photos within tolerance on all six sliders, the cross-validated choice among mean /
ridge / series 14 % — picking among many methods on a handful of examples is itself noisy.

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
FOLDS = 5
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


def _beta(model: np.ndarray, truth: np.ndarray) -> float:
    dm, dt = model - model.mean(), truth - truth.mean()
    denom = float(dm @ dm)
    return float(np.clip((dm @ dt) / denom, 0.0, 1.0)) if denom > 0 else 0.0


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


def _predict(method: str, truth, model_ref, X_ref, model_new, X_new, t_ref=None, t_new=None) -> np.ndarray:
    mean = float(truth.mean())
    if method == "series":
        return truth[np.argmin(np.abs(t_new[:, None] - t_ref[None, :]), axis=1)]
    if method == "mean":
        return np.full(len(X_new), mean)
    if method == "model":
        return mean + _beta(model_ref, truth) * (model_new - model_ref.mean())
    if method == "blend":
        return 0.5 * (mean + _ridge(X_ref, truth)(X_new)) + 0.5 * _similar(X_ref, truth, X_new)
    return mean + _ridge(X_ref, truth)(X_new)


def _choose(truth, model_ref, X_ref, tolerance: float, t_ref=None) -> str:
    """Method with the most held-out references within tolerance; ties keep the simpler one.

    model_ref None: no profile — the choice is between ``blend`` and, with capture times,
    ``series`` (see the module docstring for why not more).
    """
    k = len(truth)
    hits = {"blend": 0} if model_ref is None else {"mean": 0, "model": 0, "ridge": 0}
    if t_ref is not None:
        hits["series"] = 0
    if len(hits) == 1:
        return next(iter(hits))
    # Folds are random, not consecutive: with times, a consecutive fold would hide the
    # neighbours "series" relies on, unlike the real case (examples spread over the shoot).
    order = np.random.default_rng(0).permutation(k)
    for fold in np.array_split(order, min(FOLDS, k)):
        train = np.setdiff1d(np.arange(k), fold)
        for method in hits:
            pred = _predict(method, truth[train], None if model_ref is None else model_ref[train],
                            X_ref[train], None if model_ref is None else model_ref[fold], X_ref[fold],
                            None if t_ref is None else t_ref[train],
                            None if t_ref is None else t_ref[fold])
            hits[method] += int(np.sum(np.abs(pred - truth[fold]) <= tolerance))
    return max(hits, key=lambda m: (hits[m], m == "blend", m == "mean", m == "model", m == "series"))


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
    prediction. reference_times / times: capture times in seconds (both or neither) — enable
    the ``series`` method. reference_model and model None: no profile — the look comes from
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
    params = [p for p in TOLERANCE if all(p in r for r in references) and (not with_model or (
        all(p in m for m in reference_model) and all(p in m for m in model)))]
    for p in params:
        truth = np.array([r[p] for r in references], dtype=float)
        m_ref = np.array([m[p] for m in reference_model], dtype=float) if with_model else None
        m_new = np.array([m[p] for m in model], dtype=float) if with_model else None
        lit = with_light and p in LIGHT_SLIDERS and len(X_new) > 0
        F_ref, F_new = (X_ref_light, X_new_light) if lit else (X_ref, X_new)
        if with_camera and p in CAMERA_SLIDERS and len(X_new) > 0:
            F_ref, F_new = X_ref_camera, X_new_camera
        method = "mean" if len(truth) < MIN_FOR_CHOICE else _choose(truth, m_ref, F_ref, TOLERANCE[p], t_ref)
        methods[p] = method
        if not out:
            continue
        for row, value in zip(out, _predict(method, truth, m_ref, F_ref, m_new, F_new, t_ref, t_new)):
            row[p] = float(value)
    return out, methods
