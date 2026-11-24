"""Cull job through the worker runtime: culling features computed once per photo and kept in
its analysis, one decision per photo with a usable preview, the job COMPLETED."""

from __future__ import annotations

import io
import uuid

import fakeredis
import pytest
from PIL import Image, ImageDraw

from calotype_domain.jobs import JobKind
from calotype_io import MemoryBlobStore
from calotype_persistence.memory import MemoryStore
from calotype_queue.constants import QUEUE_CULL
from calotype_queue.envelope import JobEnvelopeV1
from calotype_worker_runtime import Services, process_one

from calotype_cull_worker.cli import FEATURES_KEY, cull_worker

WORKER = cull_worker(faces=None)  # no face models needed for these synthetic previews


def _jpeg(stripes: int) -> bytes:
    img = Image.new("RGB", (160, 120), (120, 120, 120))
    d = ImageDraw.Draw(img)
    for x in range(0, 160, max(4, 40 // stripes)):
        d.line([x, 0, x, 120], fill=(250, 250, 250), width=1)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def services(store) -> Services:
    return Services(redis=fakeredis.FakeRedis(decode_responses=True), stores=store.scope,
                    blobs=MemoryBlobStore())


def _photo(store, services, i: int, *, preview=True, rating=None):
    photo_id = uuid.uuid4()
    key = services.blobs.put_preview(photo_id, _jpeg(i + 1)) if preview else f"photos/{photo_id}.jpg"
    return store.photos.create(photo_id=photo_id, lr_catalog_uuid=str(photo_id), s3_key=key, exif_snapshot={},
                               lr_develop_settings={}, lr_metadata={"rating": rating} if rating else {})


def _run(store, services, photos):
    payload = {"schema_version": "cull-request-v1", "photo_ids": [str(p.id) for p in photos]}
    job = store.jobs.create(job_id=uuid.uuid4(), kind=JobKind.CULL, payload_schema_version="cull-request-v1",
                            payload=payload, correlation_id=None, idempotency_key=None)
    services.redis.rpush(QUEUE_CULL, JobEnvelopeV1(job_id=str(job.id), job_kind="cull", payload=payload).dumps())
    assert process_one(WORKER, services) is True
    return store.jobs.get(job.id)


def test_each_photo_with_a_preview_gets_a_decision(store, services):
    photos = [_photo(store, services, i) for i in range(4)]
    no_preview = _photo(store, services, 9, preview=False)
    job = _run(store, services, photos + [no_preview])
    assert job.status == "completed"
    results = {r.photo_id: r for r in store.cull_results.for_job(job.id)}
    assert set(results) == {p.id for p in photos}
    assert all(r.bucket in {"keep", "uncertain", "reject"} and r.method == "rules" for r in results.values())
    for p in photos:
        assert FEATURES_KEY in store.photos.get(p.id).analysis
    assert store.photos.get(no_preview.id).analysis == {}


def test_cached_features_are_used_without_the_preview(store, services):
    photos = [_photo(store, services, i) for i in range(3)]
    _run(store, services, photos)
    services.blobs.objects.clear()
    job = _run(store, services, photos)
    assert job.status == "completed"
    assert len(store.cull_results.for_job(job.id)) == 3
