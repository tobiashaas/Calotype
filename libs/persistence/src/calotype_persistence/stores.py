"""Stores: the data access the API's routes need, as one small interface.

A `Store` bundles one store per record kind (jobs, photos, profiles, feature vectors, edit
results, cull results) — what the API's routes and the workers read and write. Two adapters
implement it:

- `SqlStore` (here) — the SQLAlchemy repositories, bound to one session (one unit of work:
  the caller commits or rolls back the session; `store_scope` does both).
- `MemoryStore` (`calotype_persistence.memory`) — dicts of real ORM records, for tests of the
  API and the workers; no database.

Both return the ORM models (`Job`, `Photo`, …), so callers read real fields and a missing one
fails instead of silently returning a mock. `tests/test_store_contract.py` runs the same
assertions against both adapters.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from calotype_domain.jobs import JobKind, JobStatus
from calotype_domain.profiles import ProfileStatus
from calotype_persistence.models import CullResult, EditResult, FeatureVector, Job, Photo, Profile
from calotype_persistence.repositories.cull_results import CullResultRepository
from calotype_persistence.repositories.edit_results import EditResultRepository
from calotype_persistence.repositories.feature_vectors import FeatureVectorRepository
from calotype_persistence.repositories.jobs import JobRepository
from calotype_persistence.repositories.photos import PhotoRepository
from calotype_persistence.repositories.profiles import ProfileRepository
from calotype_persistence.session import session_scope


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

    def set_status(
        self,
        job_id: uuid.UUID,
        status: JobStatus,
        *,
        failure_reason: str | None = None,
        failure_code: str | None = None,
    ) -> Job | None:
        """RUNNING also starts the progress clock; reason and code only with FAILED."""
        ...

    def touch(self, job_id: uuid.UUID) -> None:
        """Record progress of a running job (once per processed photo)."""
        ...

    def find_stuck(self, older_than: datetime, kinds: list[str] | None = None) -> list[Job]:
        """RUNNING jobs without progress (last touch, else start) since before `older_than`."""
        ...

    def reset_to_queued(self, job_id: uuid.UUID) -> Job | None: ...


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

    def merge_analysis(self, photo_id: uuid.UUID, analysis: dict[str, Any]) -> None:
        """Add keys to the photo's analysis (existing keys are replaced)."""
        ...

    def set_feature_vector_id(self, photo_id: uuid.UUID, feature_vector_id: uuid.UUID) -> None: ...


class FeatureVectorStore(Protocol):
    def get(self, photo_id: uuid.UUID, version: str) -> FeatureVector | None:
        """The photo's vector of one feature version."""
        ...

    def create(
        self, *, vector_id: uuid.UUID, photo_id: uuid.UUID, model_version: str, vector: list[float]
    ) -> FeatureVector: ...


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

    def set_status(
        self, profile_id: uuid.UUID, status: ProfileStatus, *, failure_reason: str | None = None
    ) -> Profile | None: ...

    def set_artifact(
        self,
        profile_id: uuid.UUID,
        *,
        model_artifact_key: str,
        lr_output_keys: list[str] | None = None,
        retouch: dict[str, Any] | None = None,
    ) -> Profile | None:
        """The trained model's key and the learned mask strengths (empty → None)."""
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
        kept_crop: bool | None = None,
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
    feature_vectors: FeatureVectorStore
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

    def set_status(self, job_id, status, **fields):
        return JobRepository.set_status(self._s, job_id, status, **fields)

    def touch(self, job_id):
        JobRepository.touch(self._s, job_id)

    def find_stuck(self, older_than, kinds=None):
        return JobRepository.find_stuck(self._s, older_than, kinds)

    def reset_to_queued(self, job_id):
        return JobRepository.reset_to_queued(self._s, job_id)


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

    def merge_analysis(self, photo_id, analysis):
        PhotoRepository.merge_analysis(self._s, photo_id, analysis)

    def set_feature_vector_id(self, photo_id, feature_vector_id):
        PhotoRepository.set_feature_vector_id(self._s, photo_id, feature_vector_id)


class _SqlFeatureVectors:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, photo_id, version):
        return FeatureVectorRepository.get_by_photo_id(self._s, photo_id, version)

    def create(self, **fields):
        return FeatureVectorRepository.create(self._s, **fields)


class _SqlProfiles:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, profile_id):
        return ProfileRepository.get_by_id(self._s, profile_id)

    def list_all(self):
        return ProfileRepository.list_all(self._s)

    def create(self, **fields):
        return ProfileRepository.create(self._s, **fields)

    def set_status(self, profile_id, status, **fields):
        return ProfileRepository.set_status(self._s, profile_id, status, **fields)

    def set_artifact(self, profile_id, **fields):
        return ProfileRepository.set_artifact(self._s, profile_id, **fields)


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
        self.feature_vectors: FeatureVectorStore = _SqlFeatureVectors(session)
        self.edit_results: EditResultStore = _SqlEditResults(session)
        self.cull_results: CullResultStore = _SqlCullResults(session)


@contextmanager
def store_scope(factory: sessionmaker[Session]) -> Iterator[SqlStore]:
    """One unit of work: a `SqlStore` in a new session, committed on success, rolled back on
    error (what the workers open per photo)."""
    with session_scope(factory) as session:
        yield SqlStore(session)
