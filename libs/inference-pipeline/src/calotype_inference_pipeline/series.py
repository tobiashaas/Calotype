"""Consistent series: photos of the same scene get exposure and white balance that agree.

Predicting every photo on its own makes a burst of the same moment flicker: five frames of the
first kiss come out with five slightly different exposures. After HaCohen et al., *Optimizing
Color Consistency in Photo Collections* (SIGGRAPH 2013), the photos of a shoot form a graph:
two photos are linked when they were taken close in time *and* look alike. A quadratic cost keeps
linked photos close to each other and every photo close to its own prediction; photos the
photographer edited are fixed and pull their series towards them.

Per slider and per connected series this is one small linear system (numpy, no model):

    minimise  sum_i (x_i - p_i)^2  +  strength * sum_ij w_ij (x_i - x_j)^2,   x_fixed = given

Only sliders that should be the same within a scene are smoothed (`SLIDERS`). Without capture
times nothing is linked and every value stays as it was.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

# Exposure and white balance belong to the light of a scene; contrast, highlights … follow the
# content of each frame and stay per photo.
SLIDERS = ("exposure", "temp", "tint")
# Photos further apart than this are never one series.
MAX_GAP_SECONDS = 20.0
# Weight falls to 1/e after this many seconds …
TIME_SCALE_SECONDS = 6.0
# … and with the distance between the feature vectors (RMS of the z-scored difference: two
# unrelated photos are ~1.4 apart, near-duplicates well below 0.5).
FEATURE_SCALE = 0.6
MIN_WEIGHT = 0.05
# A feature's scale is at least this share of its mean size (see `links`).
RELATIVE_FLOOR = 0.1
# How hard linked photos are pulled together: at a weight of 1 the pull between two photos
# counts this many times as much as staying at the own prediction.
STRENGTH = 4.0


def links(
    features: Sequence[Sequence[float]], times: Sequence[float]
) -> list[tuple[int, int, float]]:
    """Pairs (i, j, weight) of photos that belong to one series: close in time and alike."""
    n = len(times)
    if n < 2:
        return []
    X = np.asarray(features, dtype=float)
    # Scale per feature: its spread over the selection, but never less than a share of its
    # size — a selection that is one single burst has almost no spread of its own, and its
    # tiny differences must not look like different scenes.
    scale = np.maximum(X.std(axis=0), RELATIVE_FLOOR * np.abs(X).mean(axis=0))
    keep = scale > 1e-9
    Z = X[:, keep] / scale[keep] if keep.any() else np.zeros((n, 1))
    t = np.asarray(times, dtype=float)
    order = np.argsort(t, kind="stable")
    out: list[tuple[int, int, float]] = []
    for a in range(n):
        i = int(order[a])
        for b in range(a + 1, n):
            j = int(order[b])
            gap = float(t[j] - t[i])
            if gap > MAX_GAP_SECONDS:
                break
            distance = float(np.sqrt(np.mean((Z[i] - Z[j]) ** 2)))
            weight = float(np.exp(-gap / TIME_SCALE_SECONDS) * np.exp(-((distance / FEATURE_SCALE) ** 2)))
            if weight >= MIN_WEIGHT:
                out.append((min(i, j), max(i, j), weight))
    return out


def _components(n: int, pairs: Sequence[tuple[int, int, float]]) -> list[list[int]]:
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j, _ in pairs:
        parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def smooth(
    values: Sequence[Mapping[str, float]],
    features: Sequence[Sequence[float]],
    times: Sequence[float] | None,
    fixed: Sequence[bool] | None = None,
    sliders: Sequence[str] = SLIDERS,
    strength: float = STRENGTH,
) -> list[dict[str, float]]:
    """The values with the sliders of each series pulled together.

    values: one dict per photo (predictions, and for fixed photos the photographer's values);
    fixed: True for photos that must keep their values (edited examples). Photos that lack a
    slider take no part for that slider. Returns new dicts; the input is not changed.
    """
    out = [dict(v) for v in values]
    n = len(out)
    if times is None or n < 2 or len(times) != n or len(features) != n:
        return out
    pinned = [bool(f) for f in fixed] if fixed is not None else [False] * n
    pairs = links(features, times)
    for group in _components(n, pairs):
        members = set(group)
        edges = [(i, j, w) for i, j, w in pairs if i in members and j in members]
        for slider in sliders:
            nodes = [i for i in group if slider in out[i]]
            free = [i for i in nodes if not pinned[i]]
            if len(nodes) < 2 or not free:
                continue
            index = {node: k for k, node in enumerate(nodes)}
            laplacian = np.zeros((len(nodes), len(nodes)))
            for i, j, w in edges:
                if i in index and j in index:
                    a, b = index[i], index[j]
                    laplacian[a, a] += w
                    laplacian[b, b] += w
                    laplacian[a, b] -= w
                    laplacian[b, a] -= w
            current = np.array([out[i][slider] for i in nodes], dtype=float)
            f = [index[i] for i in free]
            c = [index[i] for i in nodes if pinned[i]]
            system = np.eye(len(f)) + strength * laplacian[np.ix_(f, f)]
            target = current[f] - (strength * laplacian[np.ix_(f, c)] @ current[c] if c else 0.0)
            solved = np.linalg.solve(system, target)
            for node, value in zip(free, solved):
                out[node][slider] = float(value)
    return out


def spread(
    values: Sequence[Mapping[str, float]],
    features: Sequence[Sequence[float]],
    times: Sequence[float],
    slider: str,
) -> float | None:
    """Yardstick: the weighted mean absolute difference of a slider between linked photos.

    Compare the predictions' spread with the spread of the photographer's own edits of the same
    photos (PPR10K's group-level consistency). None when no two linked photos carry the slider.
    """
    total = weight_sum = 0.0
    for i, j, w in links(features, times):
        if slider in values[i] and slider in values[j]:
            total += w * abs(float(values[i][slider]) - float(values[j][slider]))
            weight_sum += w
    return total / weight_sum if weight_sum else None
