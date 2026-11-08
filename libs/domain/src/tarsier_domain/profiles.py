"""Profile lifecycle states (transport- and ORM-free)."""

from __future__ import annotations

from enum import StrEnum


class ProfileStatus(StrEnum):
    DRAFT = "draft"
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"
