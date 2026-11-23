"""One living profile: retraining it merges everything it has learned from so far."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID


def merged_training(
    earlier_payloads: Iterable[Mapping[str, Any]],
    photo_ids: Iterable[UUID],
    untouched: Mapping[str, float] | None,
) -> tuple[list[UUID], dict[str, float]]:
    """Training photos and preset placeholders of a retrain: the earlier train jobs' photos
    (in their order, each once) followed by the new ones; placeholders of all jobs, the newest
    value per Lightroom key winning. Each photo is read with its *current* settings by the
    worker, so a correction made since the last training is what the profile learns."""
    ids: dict[UUID, None] = {}
    merged: dict[str, float] = {}
    for payload in earlier_payloads:
        for raw in payload.get("photo_ids") or ():
            ids.setdefault(UUID(str(raw)), None)
        merged.update(payload.get("untouched") or {})
    for pid in photo_ids:
        ids.setdefault(pid, None)
    merged.update(untouched or {})
    return list(ids), merged
