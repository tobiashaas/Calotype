"""One living profile: retraining it merges everything it has learned from so far."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple
from uuid import UUID


class MergedTraining(NamedTuple):
    photo_ids: list[UUID]
    untouched: dict[str, float]
    accepted: list[UUID]


def merged_training(
    earlier_payloads: Iterable[Mapping[str, Any]],
    photo_ids: Iterable[UUID],
    untouched: Mapping[str, float] | None,
    accepted: Iterable[UUID] = (),
) -> MergedTraining:
    """Training photos, preset placeholders and Accepted photos of a retrain: the earlier train
    jobs' photos (in their order, each once) followed by the new ones; placeholders of all
    jobs, the newest value per Lightroom key winning; every photo accepted in any of them (an
    acceptance stays the photographer's decision, else a retrain would forget photos it learned
    before). Each photo is read with its *current* settings by the worker, so a correction made
    since the last training is what the profile learns."""
    ids: dict[UUID, None] = {}
    merged: dict[str, float] = {}
    accepted_ids: dict[UUID, None] = {}
    for payload in earlier_payloads:
        for raw in payload.get("photo_ids") or ():
            ids.setdefault(UUID(str(raw)), None)
        for raw in payload.get("accepted") or ():
            accepted_ids.setdefault(UUID(str(raw)), None)
        merged.update(payload.get("untouched") or {})
    for pid in photo_ids:
        ids.setdefault(pid, None)
    for pid in accepted:
        accepted_ids.setdefault(pid, None)
    merged.update(untouched or {})
    return MergedTraining(list(ids), merged, list(accepted_ids))
