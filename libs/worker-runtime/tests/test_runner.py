"""The worker runner across its seams: Redis (fakeredis), the store (MemoryStore) and the
blob store (MemoryBlobStore). Every outcome is read where the rest of the system sees it — the
queue, the DLQ, the job row."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from calotype_domain.failures import ProfileNotReadyError, TooFewPhotosError
from calotype_domain.jobs import JobKind, JobStatus
from calotype_io import MemoryBlobStore
from calotype_persistence.memory import MemoryStore
from calotype_queue.constants import QUEUE_CULL, QUEUE_INFERENCE, QUEUE_TRAIN, dlq_name
from calotype_queue.envelope import JobEnvelopeV1
from calotype_queue.payloads import CullPayloadV1
from calotype_worker_runtime import JobContext, Services, Worker, process_one, reap_stuck_jobs


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def services(store) -> Services:
    return Services(redis=fakeredis.FakeRedis(decode_responses=True), stores=store.scope,
                    blobs=MemoryBlobStore())


def _worker(handler, **kw) -> Worker:
    return Worker(name="cull", queue=QUEUE_CULL, kind="cull", payload_model=CullPayloadV1,
                  handler=handler, **kw)


def _job(store, kind=JobKind.CULL):
    return store.jobs.create(job_id=uuid.uuid4(), kind=kind, payload_schema_version="cull-request-v1",
                             payload={}, correlation_id=None, idempotency_key=None)


def _enqueue(services, job, *, kind="cull", payload=None, queue=QUEUE_CULL) -> str:
    payload = payload if payload is not None else {"schema_version": "cull-request-v1",
                                                    "photo_ids": [str(uuid.uuid4())]}
    raw = JobEnvelopeV1(job_id=str(job.id), job_kind=kind, payload=payload,
                        trace_context={"request_id": "req-1"}).dumps()
    services.redis.rpush(queue, raw)
    return raw


def _dlq(services, queue=QUEUE_CULL) -> list[dict]:
    return [json.loads(item) for item in services.redis.lrange(dlq_name(queue), 0, -1)]


def _never(_ctx):
    raise AssertionError("the handler must not run")


def test_empty_queue_is_no_work(services, monkeypatch):
    monkeypatch.setattr("calotype_worker_runtime.runner.BLPOP_TIMEOUT_SECONDS", 1)
    assert process_one(_worker(_never), services) is False


def test_invalid_envelope_goes_to_the_dlq(services):
    services.redis.rpush(QUEUE_CULL, '{"not": "an envelope"}')
    assert process_one(_worker(_never), services) is True
    [item] = _dlq(services)
    assert item == {"reason": "invalid_envelope", "envelope": {"not": "an envelope"}}


def test_wrong_kind_goes_to_the_dlq_and_the_job_is_untouched(services, store):
    job = _job(store, JobKind.TRAIN)
    _enqueue(services, job, kind="train")
    assert process_one(_worker(_never), services) is True
    [item] = _dlq(services)
    assert item["reason"] == "unexpected_job_kind:train"
    assert store.jobs.get(job.id).status == "queued"


def test_invalid_payload_goes_to_the_dlq_and_the_job_stays_queued(services, store):
    job = _job(store)
    _enqueue(services, job, payload={"schema_version": "cull-request-v1", "photo_ids": []})
    assert process_one(_worker(_never), services) is True
    assert [i["reason"] for i in _dlq(services)] == ["invalid_payload"]
    assert store.jobs.get(job.id).status == "queued"


def test_success_completes_the_job_with_progress(services, store):
    job = _job(store)
    seen = {}

    def handler(ctx: JobContext[CullPayloadV1]) -> None:
        seen["payload"] = ctx.payload
        seen["status"] = store.jobs.get(ctx.job_id).status
        seen["started"] = store.jobs.get(ctx.job_id).last_progress_at
        ctx.progress()

    _enqueue(services, job)
    assert process_one(_worker(handler), services) is True
    got = store.jobs.get(job.id)
    assert (got.status, got.failure_reason, got.failure_code) == ("completed", None, None)
    assert seen["status"] == "running"
    assert isinstance(seen["payload"], CullPayloadV1) and len(seen["payload"].photo_ids) == 1
    assert got.last_progress_at >= seen["started"]
    assert _dlq(services) == []


def test_domain_error_fails_the_job_with_its_code_and_dead_letters(services, store):
    job = _job(store)
    failed_in_same_unit = {}

    def handler(ctx):
        raise TooFewPhotosError("only 2 usable training photos, need at least 3")

    def on_failure(ctx, s, reason):
        failed_in_same_unit["status"] = s.jobs.get(ctx.job_id).status
        failed_in_same_unit["reason"] = reason

    raw = _enqueue(services, job)
    assert process_one(_worker(handler, on_failure=on_failure), services) is True
    got = store.jobs.get(job.id)
    assert got.status == "failed"
    assert got.failure_code == "too_few_photos"
    assert got.failure_reason == "TooFewPhotosError: only 2 usable training photos, need at least 3"
    assert failed_in_same_unit == {"status": "failed", "reason": got.failure_reason}
    [item] = _dlq(services)
    assert item == {"reason": "processing_error", "envelope": json.loads(raw)}


def test_any_other_error_is_a_processing_error_with_a_short_reason(services, store):
    job = _job(store)

    def handler(ctx):
        raise RuntimeError("x" * 2000)

    _enqueue(services, job)
    process_one(_worker(handler), services)
    got = store.jobs.get(job.id)
    assert got.failure_code == "processing_error"
    assert got.failure_reason.startswith("RuntimeError: xxx") and len(got.failure_reason) == 500


def test_completed_in_the_handlers_unit_of_work_stays_completed(services, store):
    job = _job(store)

    def handler(ctx):
        with ctx.store() as s:
            ctx.complete(s)
        s.jobs.set_status(ctx.job_id, JobStatus.RUNNING)  # the runner must not complete twice

    _enqueue(services, job)
    process_one(_worker(handler), services)
    assert store.jobs.get(job.id).status == "running"


def test_handing_on_keeps_the_job_running_and_bumps_the_attempt(services, store):
    job = _job(store, JobKind.EDIT)
    payload = {"schema_version": "cull-request-v1", "photo_ids": [str(uuid.uuid4())]}

    def handler(ctx):
        ctx.forward_to_inference()

    _enqueue(services, job, payload=payload)
    process_one(_worker(handler), services)
    assert store.jobs.get(job.id).status == "running"
    [forwarded] = services.redis.lrange(QUEUE_INFERENCE, 0, -1)
    env = JobEnvelopeV1.loads(forwarded)
    assert (env.job_id, env.attempt, env.payload) == (str(job.id), 1, payload)


def test_profile_not_ready_has_its_code(services, store):
    job = _job(store)

    def handler(ctx):
        raise ProfileNotReadyError("profile x has no model artifact")

    _enqueue(services, job)
    process_one(_worker(handler), services)
    assert store.jobs.get(job.id).failure_code == "profile_not_ready"


# --- reaper ----------------------------------------------------------------------------------


def test_reaper_requeues_only_its_own_stuck_kinds(services, store):
    stuck_train, stuck_edit, fresh_train = _job(store, JobKind.TRAIN), _job(store, JobKind.EDIT), _job(store, JobKind.TRAIN)
    for job in (stuck_train, stuck_edit, fresh_train):
        store.jobs.set_status(job.id, JobStatus.RUNNING)
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=30)
    for job in (stuck_train, stuck_edit):
        job.started_at = job.last_progress_at = long_ago

    n = reap_stuck_jobs(store.scope, queue_name=QUEUE_TRAIN, publisher=services.publisher, kinds=["train"])
    assert n == 1
    assert store.jobs.get(stuck_train.id).status == "queued"
    assert store.jobs.get(stuck_edit.id).status == "running"
    assert store.jobs.get(fresh_train.id).status == "running"
    [requeued] = services.redis.lrange(QUEUE_TRAIN, 0, -1)
    assert JobEnvelopeV1.loads(requeued).job_id == str(stuck_train.id)
