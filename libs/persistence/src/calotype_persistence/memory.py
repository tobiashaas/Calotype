"""In-memory adapter of the `Store` interface — for tests of the API and the workers.

Records are the real ORM models (`Job`, `Photo`, …), kept in dicts and never attached to a
session, so tests read and write real fields. Fields the database would fill on insert
(status, version, `{}` defaults, `created_at`) are set here the same way. The contract suite
(`tests/test_store_contract.py`) keeps this adapter and `SqlStore` in step.

Not thread-safe and not transactional: a test owns its `MemoryStore`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from calotype_domain.jobs import JobKind, JobStatus
from calotype_domain.profiles import ProfileStatus
from calotype_persistence.models import CullResult, EditResult, Job, Photo, Profile


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _MemoryJobs:
    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, Job] = {}

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._jobs.get(job_id)

    def get_by_idempotency_key(self, key: str) -> Job | None:
        return next((j for j in self._jobs.values() if j.idempotency_key == key), None)

    def list_for_profile(self, profile_id: uuid.UUID, kind: JobKind) -> list[Job]:
        return [j for j in self._jobs.values() if j.profile_id == profile_id and j.kind == kind.value]

    def create(
        self,
        *,
        job_id: uuid.UUID,
        kind: JobKind,
        payload_schema_version: str,
        payload: dict[str, Any],
        correlation_id: str | None,
        idempotency_key: str | None,
        profile_id: uuid.UUID | None = None,
    ) -> Job:
        if idempotency_key is not None and self.get_by_idempotency_key(idempotency_key):
            raise ValueError(f"idempotency key {idempotency_key!r} already used")
        now = _now()
        job = Job(
            id=job_id, kind=kind.value, status=JobStatus.QUEUED.value,
            payload_schema_version=payload_schema_version, payload=payload,
            correlation_id=correlation_id, idempotency_key=idempotency_key, profile_id=profile_id,
            failure_reason=None, started_at=None, last_progress_at=None,
            created_at=now, updated_at=now,
        )
        self._jobs[job_id] = job
        return job


class _MemoryPhotos:
    def __init__(self) -> None:
        self._photos: dict[uuid.UUID, Photo] = {}

    def get(self, photo_id: uuid.UUID) -> Photo | None:
        return self._photos.get(photo_id)

    def get_by_lr_catalog_uuid(self, lr_catalog_uuid: str) -> Photo | None:
        return next((p for p in self._photos.values() if p.lr_catalog_uuid == lr_catalog_uuid), None)

    def create(
        self,
        *,
        photo_id: uuid.UUID,
        lr_catalog_uuid: str,
        s3_key: str,
        exif_snapshot: dict[str, Any],
        lr_develop_settings: dict[str, Any],
        lr_metadata: dict[str, Any] | None = None,
    ) -> Photo:
        if self.get_by_lr_catalog_uuid(lr_catalog_uuid):
            raise ValueError(f"photo {lr_catalog_uuid!r} already stored")
        photo = Photo(
            id=photo_id, lr_catalog_uuid=lr_catalog_uuid, s3_key=s3_key,
            exif_snapshot=exif_snapshot, lr_develop_settings=lr_develop_settings,
            lr_metadata=lr_metadata or {}, analysis={}, feature_vector_id=None, created_at=_now(),
        )
        self._photos[photo_id] = photo
        return photo

    def refresh(
        self,
        photo: Photo,
        *,
        exif_snapshot: dict[str, Any],
        lr_develop_settings: dict[str, Any],
        lr_metadata: dict[str, Any],
    ) -> Photo:
        photo.exif_snapshot = exif_snapshot
        photo.lr_develop_settings = lr_develop_settings
        photo.lr_metadata = lr_metadata
        return photo


class _MemoryProfiles:
    def __init__(self) -> None:
        self._profiles: dict[uuid.UUID, Profile] = {}

    def get(self, profile_id: uuid.UUID) -> Profile | None:
        return self._profiles.get(profile_id)

    def list_all(self) -> list[Profile]:
        return list(reversed(self._profiles.values()))

    def create(
        self,
        *,
        profile_id: uuid.UUID,
        name: str,
        genre: str,
        format_type: str,
        color_type: str,
        base_preset: dict[str, Any] | None,
    ) -> Profile:
        now = _now()
        profile = Profile(
            id=profile_id, name=name, genre=genre, format_type=format_type, color_type=color_type,
            status=ProfileStatus.DRAFT.value, version=1, base_preset=base_preset, retouch=None,
            model_artifact_key=None, lr_output_keys=None, failure_reason=None,
            created_at=now, updated_at=now,
        )
        self._profiles[profile_id] = profile
        return profile


class _MemoryEditResults:
    def __init__(self) -> None:
        self._results: dict[tuple[uuid.UUID, uuid.UUID], EditResult] = {}

    def for_job(self, job_id: uuid.UUID) -> list[EditResult]:
        return [r for (j, _), r in self._results.items() if j == job_id]

    def upsert(
        self,
        *,
        result_id: uuid.UUID,
        job_id: uuid.UUID,
        photo_id: uuid.UUID,
        profile_id: uuid.UUID | None,
        lr_settings: dict[str, Any],
        s3_key: str | None = None,
        retouch: dict[str, Any] | None = None,
    ) -> None:
        existing = self._results.get((job_id, photo_id))
        self._results[(job_id, photo_id)] = EditResult(
            id=existing.id if existing else result_id, job_id=job_id, photo_id=photo_id,
            profile_id=profile_id, lr_settings=lr_settings, s3_key=s3_key, retouch=retouch,
            created_at=existing.created_at if existing else _now(),
        )


class _MemoryCullResults:
    def __init__(self) -> None:
        self._results: dict[tuple[uuid.UUID, uuid.UUID], CullResult] = {}

    def for_job(self, job_id: uuid.UUID) -> list[CullResult]:
        return [r for (j, _), r in self._results.items() if j == job_id]

    def upsert(
        self,
        *,
        job_id: uuid.UUID,
        photo_id: uuid.UUID,
        bucket: str,
        score: float,
        reason: str,
        method: str,
    ) -> None:
        existing = self._results.get((job_id, photo_id))
        self._results[(job_id, photo_id)] = CullResult(
            id=existing.id if existing else uuid.uuid4(), job_id=job_id, photo_id=photo_id,
            bucket=bucket, score=score, reason=reason[:1024], method=method,
            created_at=existing.created_at if existing else _now(),
        )


class MemoryStore:
    """A `Store` in dicts: one per test, nothing shared, nothing persisted."""

    def __init__(self) -> None:
        self.jobs = _MemoryJobs()
        self.photos = _MemoryPhotos()
        self.profiles = _MemoryProfiles()
        self.edit_results = _MemoryEditResults()
        self.cull_results = _MemoryCullResults()
