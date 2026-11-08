"""Cull a set of photos: learn from the decisions the photographer already made, else use rules.

Input: features of the photos in shoot order and, per photo, an existing decision (keep /
not keep / none). With enough decided photos of both kinds the learned scorer is fitted on
them (taste is learned, ADR 005); otherwise the explainable starter rules decide. Every photo
gets a bucket (keep / uncertain / reject), a score and a short reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from tarsier_culling.analyze import PhotoFeatures
from tarsier_culling.learned import LearnedScorer
from tarsier_culling.scoring import score

MIN_PER_CLASS = 8        # decided photos needed per class before the scorer learns from them
KEEP_ABOVE = 0.62        # learned probability thresholds; between them: uncertain
REJECT_BELOW = 0.35


@dataclass(frozen=True)
class CullResult:
    name: str
    bucket: str          # keep | uncertain | reject
    score: float         # learned: keep probability 0..1; rules: summed evidence
    reason: str
    method: str          # learned | rules


def decision_from_metadata(meta: dict | None) -> bool | None:
    """A photographer's decision from Lightroom/XMP metadata: True = keep, False = not, None = none.

    Pick flag wins; otherwise 4–5 stars = keep, 1–3 stars = not keep, no stars = no decision.
    """
    meta = meta or {}
    pick = meta.get("pick_status")
    if pick == 1:
        return True
    if pick == -1:
        return False
    rating = meta.get("rating") or 0
    if rating >= 4:
        return True
    if 1 <= rating <= 3:
        return False
    return None


def cull(photos: list[PhotoFeatures], decisions: list[bool | None]) -> list[CullResult]:
    if len(photos) != len(decisions):
        raise ValueError("one decision (or None) per photo")
    decided = [i for i, d in enumerate(decisions) if d is not None]
    keeps = sum(1 for i in decided if decisions[i])
    if keeps >= MIN_PER_CLASS and len(decided) - keeps >= MIN_PER_CLASS:
        # Fit on the decided photos, but with series/ranks computed over the whole shoot.
        scorer = LearnedScorer.fit_subset(photos, decided, [bool(decisions[i]) for i in decided])
        prob = scorer.keep_probability(photos)
        reasons = scorer.explain(photos)
        return [
            CullResult(p.name, "keep" if pr >= KEEP_ABOVE else "reject" if pr < REJECT_BELOW else "uncertain",
                       round(float(pr), 3), r, "learned")
            for p, pr, r in zip(photos, prob, reasons)
        ]
    return [CullResult(d.name, d.bucket, round(float(d.score), 3), d.explanation, "rules") for d in score(photos)]
