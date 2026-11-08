"""Series grouping and an explainable baseline scorer.

The weights here are *starting values* until a scorer is learned from the photographer's
own ratings (ADR 005). The rules that matter are structural and stay:

- Technical flaws are evidence, not a veto: a strong expression softens a blur penalty.
- Laughing with closed eyes is a moment, not a closed-eyes mistake.
- Sharpness is judged relative to this shoot (percentiles), so cameras and lenses compare.
- Within a series of near-identical shots the best one is preferred, the rest go to review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from tarsier_culling.analyze import PhotoFeatures
from tarsier_culling.technical import hamming

# dHash bits between consecutive shots of the same scene. Measured on a real shoot:
# reframed shots 9–22, new scenes mostly 25+. Embeddings + capture time will replace this.
SERIES_MAX_DISTANCE = 20
KEEP_ABOVE = 0.25
REJECT_BELOW = -0.25


def group_series(photos: list[PhotoFeatures], max_distance: int = SERIES_MAX_DISTANCE) -> list[int]:
    """Series id per photo: consecutive photos (in shooting order) that look alike."""
    ids: list[int] = []
    for i, p in enumerate(photos):
        if i and hamming(p.dhash, photos[i - 1].dhash) <= max_distance:
            ids.append(ids[-1])
        else:
            ids.append((ids[-1] + 1) if ids else 0)
    return ids


MIN_PHOTOS_FOR_RELATIVE = 5   # below this, "least sharp of the shoot" means nothing


def _percentiles(values: list[float]) -> list[float]:
    """Position of each value within the shoot (0 … 1). Equal values share a rank, so two
    equally sharp photos never end up as "best" and "worst"."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < MIN_PHOTOS_FOR_RELATIVE:
        return [0.5] * n
    below = (arr[:, None] > arr[None, :]).sum(axis=1)
    equal = (arr[:, None] == arr[None, :]).sum(axis=1) - 1
    return list((below + 0.5 * equal) / (n - 1))


@dataclass
class Decision:
    name: str
    series: int
    series_size: int
    score: float
    bucket: str                                     # keep | reject | uncertain
    reasons: list[tuple[float, str]] = field(default_factory=list)

    @property
    def explanation(self) -> str:
        parts = sorted(self.reasons, key=lambda r: -abs(r[0]))[:4]
        return "; ".join(text for _, text in parts) or "nothing notable"


def score(photos: list[PhotoFeatures]) -> list[Decision]:
    series = group_series(photos)
    sharp_pct = _percentiles([p.subject_sharpness for p in photos])
    sizes = {s: series.count(s) for s in set(series)}
    # "quality" inside a series picks the best shot: sharpness compared within the series
    # (real values, not shoot rank) plus expression, minus closed eyes
    within = _within_series_sharpness(photos, series)
    quality = [
        within[i] + 0.8 * (p.smile or 0.0) - 0.8 * _closed_penalty(p)
        for i, p in enumerate(photos)
    ]
    best_in_series = {}
    for i, s in enumerate(series):
        if s not in best_in_series or quality[i] > quality[best_in_series[s]]:
            best_in_series[s] = i

    decisions = []
    for i, p in enumerate(photos):
        reasons: list[tuple[float, str]] = []
        smile = p.smile or 0.0
        expressive = smile > 0.6 or p.laughing_closed_eyes

        # sharpness, relative to this shoot; a strong moment halves the penalty
        pct = sharp_pct[i]
        if pct < 0.15:
            w = -0.5 if expressive else -1.0
            reasons.append((w * (0.15 - pct) / 0.15 * 0.8, "among the least sharp of the shoot"
                            + (" (but a strong expression)" if expressive else "")))
        elif pct > 0.7:
            reasons.append((0.25 * (pct - 0.7) / 0.3, "sharp subject"))

        # eyes and expression
        if p.laughing_closed_eyes:
            reasons.append((0.35, "laughing with closed eyes — a moment"))
        elif (p.eyes_closed or 0) > 0.6:
            reasons.append((-0.7, "eyes closed or looking down"))
        if smile > 0.3:
            reasons.append((0.5 * smile, f"smile {smile:.0%}"))

        # exposure: previews are unedited and bright backgrounds are normal, so only a
        # blown-out face or an extremely clipped frame counts
        if p.face_clipped > 0.15:
            reasons.append((-0.4, f"face overexposed ({p.face_clipped:.0%} blown)"))
        elif p.clipped_highlights > 0.35:
            reasons.append((-0.2, f"{p.clipped_highlights:.0%} of the frame blown out"))
        if p.mean_luma < 0.06:
            reasons.append((-0.3, "very dark"))

        # series: prefer the best shot, send the rest to review instead of rejecting
        size = sizes[series[i]]
        if size > 1:
            if best_in_series[series[i]] == i:
                reasons.append((0.3, f"best of a series of {size}"))
            else:
                gap = quality[best_in_series[series[i]]] - quality[i]
                # alone this only reaches "uncertain": near-duplicates are for review, not the bin
                reasons.append((-min(0.2, 0.1 + 0.1 * gap), f"a better shot of this series exists ({size} shots)"))

        total = float(sum(w for w, _ in reasons))
        bucket = "keep" if total > KEEP_ABOVE else "reject" if total < REJECT_BELOW else "uncertain"
        decisions.append(Decision(p.name, series[i], size, total, bucket, reasons))
    return decisions


def _within_series_sharpness(photos: list[PhotoFeatures], series: list[int]) -> list[float]:
    """Subject sharpness scaled 0 … 1 inside each series (0.5 if all are alike)."""
    out = [0.5] * len(photos)
    for s in set(series):
        idx = [i for i, x in enumerate(series) if x == s]
        values = [photos[i].subject_sharpness for i in idx]
        lo, hi = min(values), max(values)
        if hi - lo > 0.05:
            for i, v in zip(idx, values):
                out[i] = (v - lo) / (hi - lo)
    return out


def _closed_penalty(p: PhotoFeatures) -> float:
    if p.laughing_closed_eyes:
        return 0.0
    return 1.0 if (p.eyes_closed or 0) > 0.6 else 0.0
