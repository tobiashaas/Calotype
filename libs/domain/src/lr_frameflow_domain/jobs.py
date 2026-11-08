from __future__ import annotations

from enum import StrEnum


class JobKind(StrEnum):
    TRAIN = "train"
    EDIT = "edit"
    CULL = "cull"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
