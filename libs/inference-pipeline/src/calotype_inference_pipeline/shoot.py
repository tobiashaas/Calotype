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


def _beta(model: np.ndarray, truth: np.ndarray) -> float:
    dm, dt = model - model.mean(), truth - truth.mean()
    denom = float(dm @ dm)
    return float(np.clip((dm @ dt) / denom, 0.0, 1.0)) if denom > 0 else 0.0


def _ridge(X: np.ndarray, y: np.ndarray):
    """Fitted on the residual to the mean; returns a predictor for new rows."""
    scaler = StandardScaler().fit(X)
    reg = Ridge(alpha=RIDGE_ALPHA).fit(scaler.transform(X), y - y.mean())
    return lambda rows: reg.predict(scaler.transform(rows))


def _predict(method: str, truth, model_ref, X_ref, model_new, X_new, t_ref=None, t_new=None) -> np.ndarray:
    mean = float(truth.mean())
    if method == "series":
        return truth[np.argmin(np.abs(t_new[:, None] - t_ref[None, :]), axis=1)]
    if method == "mean":
        return np.full(len(model_new), mean)
    if method == "model":
        return mean + _beta(model_ref, truth) * (model_new - model_ref.mean())
    return mean + _ridge(X_ref, truth)(X_new)


def _choose(truth, model_ref, X_ref, tolerance: float, t_ref=None) -> str:
    """Method with the most held-out references within tolerance; ties keep the simpler one."""
    k = len(truth)
    hits = {"mean": 0, "model": 0, "ridge": 0}
    if t_ref is not None:
        hits["series"] = 0
    # Folds are random, not consecutive: with times, a consecutive fold would hide the
    # neighbours "series" relies on, unlike the real case (examples spread over the shoot).
    order = np.random.default_rng(0).permutation(k)
    for fold in np.array_split(order, min(FOLDS, k)):
        train = np.setdiff1d(np.arange(k), fold)
        for method in hits:
            pred = _predict(method, truth[train], model_ref[train], X_ref[train],
                            model_ref[fold], X_ref[fold],
                            None if t_ref is None else t_ref[train],
                            None if t_ref is None else t_ref[fold])
            hits[method] += int(np.sum(np.abs(pred - truth[fold]) <= tolerance))
    return max(hits, key=lambda m: (hits[m], m == "mean", m == "model", m == "series"))


def calibrate(
    references: Sequence[Mapping[str, float]],
    reference_model: Sequence[Mapping[str, float]],
    reference_features: Sequence[Sequence[float]],
    model: Sequence[Mapping[str, float]],
    features: Sequence[Sequence[float]],
    reference_times: Sequence[float] | None = None,
    times: Sequence[float] | None = None,
) -> tuple[list[dict[str, float]], dict[str, str]]:
    """Predictions for the other photos of the shoot, and the method chosen per slider.

    references: the photographer's values of the edited photos; reference_model / model: the
    profile's predictions for the edited / the other photos; *_features: their feature vectors.
    Sliders missing from a reference (e.g. RAW temperature without a value) keep the model's
    prediction. reference_times / times: capture times in seconds (both or neither) — enable
    the ``series`` method.
    """
    if not references:
        raise ValueError("calibration needs at least one edited photo")
    X_ref = np.asarray(reference_features, dtype=float)
    X_new = np.asarray(features, dtype=float)
    with_times = reference_times is not None and times is not None
    t_ref = np.asarray(reference_times, dtype=float) if with_times else None
    t_new = np.asarray(times, dtype=float) if with_times else None
    out = [dict(m) for m in model]
    methods: dict[str, str] = {}
    params = [p for p in TOLERANCE if all(p in r for r in references)
              and all(p in m for m in reference_model) and all(p in m for m in model)]
    for p in params:
        truth = np.array([r[p] for r in references], dtype=float)
        m_ref = np.array([m[p] for m in reference_model], dtype=float)
        m_new = np.array([m[p] for m in model], dtype=float)
        method = "mean" if len(truth) < MIN_FOR_CHOICE else _choose(truth, m_ref, X_ref, TOLERANCE[p], t_ref)
        methods[p] = method
        if not out:
            continue
        for row, value in zip(out, _predict(method, truth, m_ref, X_ref, m_new, X_new, t_ref, t_new)):
            row[p] = float(value)
    return out, methods
