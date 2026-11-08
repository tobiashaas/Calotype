"""Shared test fixtures for the API integration tests.

Strategy: mock the four Repository classes and S3/Redis so that tests run
without Postgres or any external infrastructure. This lets CI validate routing,
request validation, and business logic without a live database.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from calotype_api.deps import get_publisher, get_session, get_storage
from calotype_api.main import app

# ---------------------------------------------------------------------------
# In-memory store — a simple dict-based fake that mimics the DB
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self) -> None:
        self.jobs: dict[str, object] = {}
        self.photos: dict[str, object] = {}
        self.profiles: dict[str, object] = {}
        self.edit_results: dict[str, list] = {}
        self.cull_results: dict[str, list] = {}


def _fake_job(job_id, kind, status, payload, payload_schema_version, correlation_id, idempotency_key, profile_id):
    j = MagicMock()
    j.id = uuid.UUID(job_id) if isinstance(job_id, str) else job_id
    j.kind = kind
    j.status = status
    j.payload = payload
    j.payload_schema_version = payload_schema_version
    j.correlation_id = correlation_id
    j.idempotency_key = idempotency_key
    j.profile_id = profile_id
    j.failure_reason = None
    return j


def _fake_profile(profile_id, name, genre, format_type, color_type, status="draft",
                  version=1, base_preset=None, model_artifact_key=None,
                  lr_output_keys=None, failure_reason=None):
    p = MagicMock()
    p.id = uuid.UUID(profile_id) if isinstance(profile_id, str) else profile_id
    p.name = name
    p.genre = genre
    p.format_type = format_type
    p.color_type = color_type
    p.status = status
    p.version = version
    p.base_preset = base_preset
    p.model_artifact_key = model_artifact_key
    p.lr_output_keys = lr_output_keys
    p.failure_reason = failure_reason
    return p


def _fake_photo(photo_id, lr_catalog_uuid, s3_key):
    ph = MagicMock()
    ph.id = uuid.UUID(photo_id) if isinstance(photo_id, str) else photo_id
    ph.lr_catalog_uuid = lr_catalog_uuid
    ph.s3_key = s3_key
    return ph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store() -> _FakeStore:
    return _FakeStore()


@pytest.fixture()
def mock_publisher():
    pub = MagicMock()
    pub.enqueue = MagicMock()
    return pub


@pytest.fixture()
def mock_storage():
    s3 = MagicMock()
    s3.put_object = MagicMock()
    return s3


@pytest.fixture()
def client(store, mock_publisher, mock_storage) -> Generator[TestClient, None, None]:
    """TestClient with all external deps replaced by in-memory fakes."""

    def _job_create(session, *, job_id, kind, payload_schema_version, payload,
                    correlation_id, idempotency_key, profile_id=None):
        j = _fake_job(str(job_id), kind.value, "queued", payload,
                      payload_schema_version, correlation_id, idempotency_key, profile_id)
        store.jobs[str(job_id)] = j
        return j

    def _job_get_by_id(session, job_id):
        return store.jobs.get(str(job_id))

    def _job_get_by_idempotency_key(session, key):
        for j in store.jobs.values():
            if j.idempotency_key == key:
                return j
        return None

    def _job_set_status(session, job_id, status, *, failure_reason=None):
        j = store.jobs.get(str(job_id))
        if j:
            j.status = status.value
            j.failure_reason = failure_reason
        return j

    def _profile_create(session, *, profile_id, name, genre, format_type, color_type,
                        base_preset=None):
        p = _fake_profile(str(profile_id), name, genre, format_type, color_type,
                          base_preset=base_preset)
        store.profiles[str(profile_id)] = p
        return p

    def _profile_get_by_id(session, profile_id):
        return store.profiles.get(str(profile_id))

    def _profile_list_all(session):
        return list(store.profiles.values())

    def _photo_create(session, *, photo_id, lr_catalog_uuid, s3_key,
                      exif_snapshot, lr_develop_settings, lr_metadata=None):
        ph = _fake_photo(str(photo_id), lr_catalog_uuid, s3_key)
        ph.lr_develop_settings = lr_develop_settings
        ph.lr_metadata = lr_metadata or {}
        store.photos[str(photo_id)] = ph
        store.photos[f"lc:{lr_catalog_uuid}"] = ph
        return ph

    def _photo_refresh(session, photo, *, exif_snapshot, lr_develop_settings, lr_metadata):
        photo.exif_snapshot = exif_snapshot
        photo.lr_develop_settings = lr_develop_settings
        photo.lr_metadata = lr_metadata
        return photo

    def _photo_get_by_id(session, photo_id):
        return store.photos.get(str(photo_id))

    def _photo_get_by_lr_catalog_uuid(session, lr_catalog_uuid):
        return store.photos.get(f"lc:{lr_catalog_uuid}")

    def _edit_result_get_all(session, job_id):
        return store.edit_results.get(str(job_id), [])

    patches = [
        patch("calotype_api.main.JobRepository.create", side_effect=_job_create),
        patch("calotype_api.main.JobRepository.get_by_id", side_effect=_job_get_by_id),
        patch("calotype_api.main.JobRepository.get_by_idempotency_key", side_effect=_job_get_by_idempotency_key),
        patch("calotype_api.main.ProfileRepository.create", side_effect=_profile_create),
        patch("calotype_api.main.ProfileRepository.get_by_id", side_effect=_profile_get_by_id),
        patch("calotype_api.main.ProfileRepository.list_all", side_effect=_profile_list_all),
        patch("calotype_api.main.PhotoRepository.create", side_effect=_photo_create),
        patch("calotype_api.main.PhotoRepository.refresh", side_effect=_photo_refresh),
        patch("calotype_api.main.PhotoRepository.get_by_id", side_effect=_photo_get_by_id),
        patch("calotype_api.main.PhotoRepository.get_by_lr_catalog_uuid", side_effect=_photo_get_by_lr_catalog_uuid),
        patch("calotype_api.main.EditResultRepository.get_all_by_job_id", side_effect=_edit_result_get_all),
        patch("calotype_api.main.CullResultRepository.get_all_by_job_id",
              side_effect=lambda session, job_id: store.cull_results.get(str(job_id), [])),
        patch("calotype_api.storage.upload_photo"),
    ]

    app.dependency_overrides[get_session] = lambda: MagicMock()
    app.dependency_overrides[get_publisher] = lambda: mock_publisher
    app.dependency_overrides[get_storage] = lambda: mock_storage

    with _nested_patches(patches):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


class _nested_patches:
    def __init__(self, patch_list):
        self._patches = patch_list
        self._mocks: list = []

    def __enter__(self):
        self._mocks = [p.start() for p in self._patches]
        return self._mocks

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()
