"""Stores: the data access the API's routes need, as one small interface.

A `Store` bundles one store per record kind (jobs, photos, profiles, edit results, cull
results). Two adapters implement it:

- `SqlStore` (here) — the SQLAlchemy repositories, bound to one session (one unit of work:
  the caller commits or rolls back the session).
- `MemoryStore` (`calotype_persistence.memory`) — dicts of real ORM records, for tests of the
  API and the workers; no database.

Both return the ORM models (`Job`, `Photo`, …), so callers read real fields and a missing one
fails instead of silently returning a mock. `tests/test_store_contract.py` runs the same
assertions against both adapters.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from sqlalchemy.orm import Session

from calotype_domain.jobs import JobKind
from calotype_persistence.models import CullResult, EditResult, Job, Photo, Profile
from calotype_persistence.repositories.cull_results import CullResultRepository
from calotype_persistence.repositories.edit_results import EditResultRepository
from calotype_persistence.repositories.jobs import JobRepository
from calotype_persistence.repositories.photos import PhotoRepository
from calotype_persistence.repositories.profiles import ProfileRepository


class JobStore(Protocol):
    def get(self, job_id: uuid.UUID) -> Job | None: ...

    def get_by_idempotency_key(self, key: str) -> Job | None: ...

    def list_for_profile(self, profile_id: uuid.UUID, kind: JobKind) -> list[Job]:
        """A profile's jobs of one kind, oldest first."""
        ...

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
        """A new job in status queued."""
        ...


class PhotoStore(Protocol):
    def get(self, photo_id: uuid.UUID) -> Photo | None: ...

    def get_by_lr_catalog_uuid(self, lr_catalog_uuid: str) -> Photo | None: ...

    def create(
        self,
        *,
        photo_id: uuid.UUID,
        lr_catalog_uuid: str,
        s3_key: str,
        exif_snapshot: dict[str, Any],
        lr_develop_settings: dict[str, Any],
        lr_metadata: dict[str, Any] | None = None,
    ) -> Photo: ...

    def refresh(
        self,
        photo: Photo,
        *,
        exif_snapshot: dict[str, Any],
        lr_develop_settings: dict[str, Any],
        lr_metadata: dict[str, Any],
    ) -> Photo:
        """Re-upload of a known photo: the preview stays, develop settings and decisions are current."""
        ...


class ProfileStore(Protocol):
    def get(self, profile_id: uuid.UUID) -> Profile | None: ...

    def list_all(self) -> list[Profile]:
        """All profiles, newest first."""
        ...

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
        """A new profile in status draft, version 1, not trained yet."""
        ...


class EditResultStore(Protocol):
    def for_job(self, job_id: uuid.UUID) -> list[EditResult]: ...

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
        """One result per photo and job; a re-run of the job replaces it."""
        ...


class CullResultStore(Protocol):
    def for_job(self, job_id: uuid.UUID) -> list[CullResult]: ...

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
        """One decision per photo and job; a re-run replaces it."""
        ...


class Store(Protocol):
    jobs: JobStore
    photos: PhotoStore
    profiles: ProfileStore
    edit_results: EditResultStore
    cull_results: CullResultStore


# ---------------------------------------------------------------------------
# SQL adapter: the repositories bound to one session
# ---------------------------------------------------------------------------


class _SqlJobs:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, job_id):
        return JobRepository.get_by_id(self._s, job_id)

    def get_by_idempotency_key(self, key):
        return JobRepository.get_by_idempotency_key(self._s, key)

    def list_for_profile(self, profile_id, kind):
        return JobRepository.list_for_profile(self._s, profile_id, kind)

    def create(self, **fields):
        return JobRepository.create(self._s, **fields)


class _SqlPhotos:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, photo_id):
        return PhotoRepository.get_by_id(self._s, photo_id)

    def get_by_lr_catalog_uuid(self, lr_catalog_uuid):
        return PhotoRepository.get_by_lr_catalog_uuid(self._s, lr_catalog_uuid)

    def create(self, **fields):
        return PhotoRepository.create(self._s, **fields)

    def refresh(self, photo, **fields):
        return PhotoRepository.refresh(self._s, photo, **fields)


class _SqlProfiles:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, profile_id):
        return ProfileRepository.get_by_id(self._s, profile_id)

    def list_all(self):
        return ProfileRepository.list_all(self._s)

    def create(self, **fields):
        return ProfileRepository.create(self._s, **fields)


class _SqlEditResults:
    def __init__(self, session: Session) -> None:
        self._s = session

    def for_job(self, job_id):
        return EditResultRepository.get_all_by_job_id(self._s, job_id)

    def upsert(self, **fields):
        EditResultRepository.upsert(self._s, **fields)


class _SqlCullResults:
    def __init__(self, session: Session) -> None:
        self._s = session

    def for_job(self, job_id):
        return CullResultRepository.get_all_by_job_id(self._s, job_id)

    def upsert(self, **fields):
        CullResultRepository.upsert(self._s, **fields)


class SqlStore:
    """The Postgres adapter: every store works in the given session (the unit of work)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs: JobStore = _SqlJobs(session)
        self.photos: PhotoStore = _SqlPhotos(session)
        self.profiles: ProfileStore = _SqlProfiles(session)
        self.edit_results: EditResultStore = _SqlEditResults(session)
        self.cull_results: CullResultStore = _SqlCullResults(session)
