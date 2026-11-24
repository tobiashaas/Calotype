"""Feature stage of an edit job through the worker runtime: every supported feature version
and the preview analysis are stored once, the job goes on to the inference queue."""

from __future__ import annotations

import io
import uuid

import fakeredis
import pytest
from PIL import Image

from calotype_domain.jobs import JobKind
from calotype_inference_pipeline import SUPPORTED_FEATURE_VERSIONS
from calotype_io import MemoryBlobStore
from calotype_persistence.memory import MemoryStore
from calotype_queue.constants import QUEUE_FEATURE, QUEUE_INFERENCE
from calotype_queue.envelope import JobEnvelopeV1
from calotype_worker_runtime import Services, process_one

from calotype_feature_worker.cli import WORKER


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (96, 64), (180, 140, 90)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def services(store) -> Services:
    return Services(redis=fakeredis.FakeRedis(decode_responses=True), stores=store.scope,
                    blobs=MemoryBlobStore())


def _photo(store, services, *, preview=True):
    photo_id = uuid.uuid4()
    key = services.blobs.put_preview(photo_id, _jpeg()) if preview else f"photos/{photo_id}.jpg"
    return store.photos.create(photo_id=photo_id, lr_catalog_uuid=str(photo_id), s3_key=key,
                               exif_snapshot={}, lr_develop_settings={})


def _run(store, services, photo_ids):
    payload = {"schema_version": "edit-request-v1", "profile_id": str(uuid.uuid4()),
               "photo_ids": [str(p) for p in photo_ids]}
    job = store.jobs.create(job_id=uuid.uuid4(), kind=JobKind.EDIT, payload_schema_version="edit-request-v1",
                            payload=payload, correlation_id=None, idempotency_key=None)
    services.redis.rpush(QUEUE_FEATURE, JobEnvelopeV1(job_id=str(job.id), job_kind="edit", payload=payload).dumps())
    assert process_one(WORKER, services) is True
    return store.jobs.get(job.id)


def test_vectors_and_analysis_are_stored_and_the_job_goes_on(store, services):
    with_preview, without = _photo(store, services), _photo(store, services, preview=False)
    job = _run(store, services, [with_preview.id, without.id, uuid.uuid4()])

    for version in SUPPORTED_FEATURE_VERSIONS:
        vec = store.feature_vectors.get(with_preview.id, version)
        assert vec is not None and any(vec.vector)
        assert store.feature_vectors.get(without.id, version) is None
    assert store.photos.get(with_preview.id).analysis["preview_size"] == [96, 64]
    assert "straighten" in store.photos.get(with_preview.id).analysis
    assert store.photos.get(without.id).analysis == {}

    assert job.status == "running"  # the inference worker completes it
    [forwarded] = services.redis.lrange(QUEUE_INFERENCE, 0, -1)
    env = JobEnvelopeV1.loads(forwarded)
    assert (env.job_id, env.attempt) == (str(job.id), 1)


def test_a_second_job_reuses_what_is_stored(store, services):
    photo = _photo(store, services)
    _run(store, services, [photo.id])
    first = {v: store.feature_vectors.get(photo.id, v).id for v in SUPPORTED_FEATURE_VERSIONS}
    services.blobs.objects.clear()  # no preview needed any more
    job = _run(store, services, [photo.id])
    assert {v: store.feature_vectors.get(photo.id, v).id for v in SUPPORTED_FEATURE_VERSIONS} == first
    assert job.status == "running"
    assert len(services.redis.lrange(QUEUE_INFERENCE, 0, -1)) == 2
