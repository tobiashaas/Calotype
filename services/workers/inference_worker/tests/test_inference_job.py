"""Inference stage of an edit job through the worker runtime: the profile's model from the blob
store, one edit result per photo with features, the job COMPLETED — or FAILED with the code
the plugin shows a message for."""

from __future__ import annotations

import random
import uuid

import fakeredis
import pytest

from calotype_domain.jobs import JobKind
from calotype_domain.profiles import ProfileStatus
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION, train_for_version
from calotype_io import MemoryBlobStore
from calotype_persistence.memory import MemoryStore
from calotype_queue.constants import QUEUE_INFERENCE, dlq_name
from calotype_queue.envelope import JobEnvelopeV1
from calotype_worker_runtime import Services, process_one

from calotype_inference_worker.cli import WORKER

UNTOUCHED = {"WhiteBalance": "As Shot", "Temperature": 5000, "Tint": 0, "Exposure2012": 0}
DIM = 153  # histstats-face-v2


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def services(store) -> Services:
    return Services(redis=fakeredis.FakeRedis(decode_responses=True), stores=store.scope,
                    blobs=MemoryBlobStore())


def _profile(store, services, *, trained=True):
    profile = store.profiles.create(profile_id=uuid.uuid4(), name="Golden Hour", genre="wedding",
                                    format_type="raw", color_type="color", base_preset=None)
    if trained:
        rng = random.Random(1)
        vectors = [[rng.random() for _ in range(DIM)] for _ in range(6)]
        targets = [{"exposure": 0.3 + 0.1 * i, "temp": 5200.0, "tint": 2.0, "contrast": 8.0} for i in range(6)]
        key = services.blobs.put_model(profile.id, CURRENT_FEATURE_VERSION,
                                       train_for_version(vectors, targets, CURRENT_FEATURE_VERSION))
        store.profiles.set_artifact(profile.id, model_artifact_key=key)
    store.profiles.set_status(profile.id, ProfileStatus.READY)
    return profile


def _photo(store, *, vector=True):
    photo_id = uuid.uuid4()
    photo = store.photos.create(photo_id=photo_id, lr_catalog_uuid=str(photo_id), s3_key=f"photos/{photo_id}.jpg",
                                exif_snapshot={}, lr_develop_settings=dict(UNTOUCHED))
    if vector:
        store.feature_vectors.create(vector_id=uuid.uuid4(), photo_id=photo_id,
                                     model_version=CURRENT_FEATURE_VERSION, vector=[0.4] * DIM)
    return photo


def _run(store, services, photos, **request):
    payload = {"schema_version": "edit-request-v1", "photo_ids": [str(p.id) for p in photos], **request}
    job = store.jobs.create(job_id=uuid.uuid4(), kind=JobKind.EDIT, payload_schema_version="edit-request-v1",
                            payload=payload, correlation_id=None, idempotency_key=None)
    services.redis.rpush(QUEUE_INFERENCE, JobEnvelopeV1(job_id=str(job.id), job_kind="edit", payload=payload,
                                                        attempt=1).dumps())
    assert process_one(WORKER, services) is True
    return store.jobs.get(job.id)


def test_every_photo_with_features_gets_a_result(store, services):
    profile = _profile(store, services)
    with_features, without = _photo(store), _photo(store, vector=False)
    job = _run(store, services, [with_features, without], profile_id=str(profile.id))
    assert (job.status, job.failure_code) == ("completed", None)
    [result] = store.edit_results.for_job(job.id)
    assert result.photo_id == with_features.id
    assert result.profile_id == profile.id
    assert "Exposure2012" in result.lr_settings and "Temperature" in result.lr_settings
    assert job.last_progress_at is not None


def test_a_profile_without_a_model_fails_as_not_ready(store, services):
    profile = _profile(store, services, trained=False)
    job = _run(store, services, [_photo(store)], profile_id=str(profile.id))
    assert (job.status, job.failure_code) == ("failed", "profile_not_ready")
    assert job.failure_reason == f"ProfileNotReadyError: profile {profile.id} has no model artifact"
    assert store.edit_results.for_job(job.id) == []
    assert len(services.redis.lrange(dlq_name(QUEUE_INFERENCE), 0, -1)) == 1


def test_learning_from_edits_without_any_edited_photo_fails_with_no_examples(store, services):
    job = _run(store, services, [_photo(store), _photo(store)], learn_from_edits=True, format_type="raw")
    assert (job.status, job.failure_code) == ("failed", "no_examples")
