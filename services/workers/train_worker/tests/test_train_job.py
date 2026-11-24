"""Train job through the worker runtime: queue (fakeredis) → handler → store and blob store
(in memory). Feature vectors are computed for freshly uploaded photos instead of failing."""

from __future__ import annotations

import io
import uuid

import fakeredis
import pytest
from PIL import Image

from calotype_domain.jobs import JobKind
from calotype_domain.profiles import ProfileStatus
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION
from calotype_io import MemoryBlobStore, model_key
from calotype_persistence.memory import MemoryStore
from calotype_queue.constants import QUEUE_TRAIN, dlq_name
from calotype_queue.envelope import JobEnvelopeV1
from calotype_worker_runtime import Services, process_one

from calotype_train_worker.cli import WORKER

EDITED = {"WhiteBalance": "Custom", "Temperature": 5600, "Tint": 4, "Exposure2012": 0.4,
          "Contrast2012": 12}


def _jpeg(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def services(store) -> Services:
    return Services(redis=fakeredis.FakeRedis(decode_responses=True), stores=store.scope,
                    blobs=MemoryBlobStore())


def _photo(store, services, i: int, *, preview: bool = True, settings=None):
    photo_id = uuid.uuid4()
    key = (services.blobs.put_preview(photo_id, _jpeg((40 * i, 120, 200 - 30 * i))) if preview
           else f"photos/{photo_id}.jpg")
    return store.photos.create(photo_id=photo_id, lr_catalog_uuid=str(photo_id), s3_key=key, exif_snapshot={},
                               lr_develop_settings={**EDITED, "Exposure2012": 0.2 * i} if settings is None else settings)


def _run(store, services, photos, *, retrain=False):
    profile = store.profiles.create(profile_id=uuid.uuid4(), name="Golden Hour", genre="wedding",
                                    format_type="raw", color_type="color", base_preset=None)
    if retrain:
        store.profiles.set_artifact(profile.id, model_artifact_key="models/old/model-v1.joblib")
        store.profiles.set_status(profile.id, ProfileStatus.READY)
    payload = {"schema_version": "train-request-v1", "profile_name": "Golden Hour", "genre": "wedding",
               "format_type": "raw", "color_type": "color", "photo_ids": [str(p.id) for p in photos],
               "profile_id": str(profile.id), "retrain": retrain}
    job = store.jobs.create(job_id=uuid.uuid4(), kind=JobKind.TRAIN, payload_schema_version="train-request-v1",
                            payload=payload, correlation_id=None, idempotency_key=None, profile_id=profile.id)
    services.redis.rpush(QUEUE_TRAIN, JobEnvelopeV1(job_id=str(job.id), job_kind="train", payload=payload).dumps())
    assert process_one(WORKER, services) is True
    return store.jobs.get(job.id), store.profiles.get(profile.id)


def test_training_computes_missing_vectors_and_readies_the_profile(store, services):
    photos = [_photo(store, services, i) for i in range(3)]
    job, profile = _run(store, services, photos)
    assert job.status == "completed"
    assert profile.status == "ready"
    key = model_key(profile.id, CURRENT_FEATURE_VERSION)
    assert profile.model_artifact_key == key
    assert services.blobs.model(key)  # the model bytes are in the bucket under the profile's key
    for p in photos:
        vec = store.feature_vectors.get(p.id, CURRENT_FEATURE_VERSION)
        assert vec is not None and len(vec.vector) == 153 and any(vec.vector)
        assert store.photos.get(p.id).feature_vector_id == vec.id


def test_a_stored_vector_counts_without_a_preview(store, services):
    photos = [_photo(store, services, i) for i in range(2)]
    no_preview = _photo(store, services, 2, preview=False)
    store.feature_vectors.create(vector_id=uuid.uuid4(), photo_id=no_preview.id,
                                 model_version=CURRENT_FEATURE_VERSION, vector=[0.5] * 153)
    job, profile = _run(store, services, photos + [no_preview])
    assert (job.status, profile.status) == ("completed", "ready")


def test_too_few_usable_photos_fail_job_and_profile(store, services):
    photos = [_photo(store, services, 0), _photo(store, services, 1), _photo(store, services, 2, preview=False)]
    job, profile = _run(store, services, photos)
    assert (job.status, job.failure_code) == ("failed", "too_few_photos")
    assert job.failure_reason == "TooFewPhotosError: only 2 usable training photos, need at least 3"
    assert (profile.status, profile.failure_reason) == ("failed", job.failure_reason)
    assert len(services.redis.lrange(dlq_name(QUEUE_TRAIN), 0, -1)) == 1


def test_a_failed_retrain_keeps_the_profile_ready_with_its_model(store, services):
    job, profile = _run(store, services, [_photo(store, services, 0)], retrain=True)
    assert (job.status, job.failure_code) == ("failed", "too_few_photos")
    assert profile.status == "ready"
    assert profile.model_artifact_key == "models/old/model-v1.joblib"
