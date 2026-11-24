"""The worker runner: everything a worker does around its job, in one place (ADR 007).

A worker is a `Worker` — its queue, the job kind it accepts, the payload model and a handler
— and `run_worker(worker)` is its whole main loop. Per message `process_one`:

1. BLPOP the worker's queue; an envelope that does not parse → DLQ ``invalid_envelope``
2. another job kind → DLQ ``unexpected_job_kind:<kind>``
3. a payload its model rejects → DLQ ``invalid_payload`` (the job keeps its status)
4. job RUNNING, then the handler with a `JobContext`
5. handler returned → job COMPLETED (unless the handler completed it inside its own unit of
   work, or handed the job on to the next queue)
6. handler raised → job FAILED with a short reason (``Type: message``, ≤ 500 chars, shown in
   Lightroom) and ``failure_code(exc)``; the worker's `on_failure` runs in the same unit of
   work; envelope → DLQ ``processing_error``; traceback to the log

`run_worker` adds what every worker process needs: logging, the heartbeat file, the stuck-job
reaper for the job kinds whose pipeline starts on this queue, and a retry when Redis is gone.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from calotype_domain.failures import failure_code
from calotype_domain.jobs import JobStatus
from calotype_io import BlobStore
from calotype_observability import configure_logging, get_logger, set_request_id, start_heartbeat_thread
from calotype_persistence.stores import Store
from calotype_queue import consumer
from calotype_queue.envelope import JobEnvelopeV1
from calotype_queue.publisher import RedisQueuePublisher

from calotype_worker_runtime.features import ComputeFeatures, FeatureStore
from calotype_worker_runtime.reaper import reap_stuck_jobs, start_reaper_thread

P = TypeVar("P", bound=BaseModel)

# A unit of work over the store: `store_scope(factory)` in production, `MemoryStore.scope` in tests.
Stores = Callable[[], AbstractContextManager[Store]]

MAX_REASON_LENGTH = 500
IDLE_SLEEP_SECONDS = 0.05
REDIS_RETRY_SECONDS = 2
BLPOP_TIMEOUT_SECONDS = 5


@dataclass
class Services:
    """What a worker runs against: Redis, the store, the blob store."""

    redis: Redis
    stores: Stores
    blobs: BlobStore
    publisher: RedisQueuePublisher = field(init=False)

    def __post_init__(self) -> None:
        self.publisher = RedisQueuePublisher(self.redis)

    @classmethod
    def from_env(cls) -> Services:
        """REDIS_URL, DATABASE_URL and the S3_* variables, as every worker always read them."""
        from calotype_io import S3BlobStore
        from calotype_persistence.session import get_session_factory
        from calotype_persistence.stores import store_scope
        from calotype_queue.publisher import redis_from_env

        factory = get_session_factory()
        return cls(redis=redis_from_env(), stores=lambda: store_scope(factory),
                   blobs=S3BlobStore.from_env())


class JobContext(Generic[P]):
    """What a handler gets: the typed payload and the job's services."""

    def __init__(self, *, job_id: UUID, envelope: JobEnvelopeV1, payload: P, services: Services,
                 features: FeatureStore, log: logging.Logger) -> None:
        self.job_id = job_id
        self.envelope = envelope
        self.payload = payload
        self.blobs = services.blobs
        self.features = features
        self.log = log
        self._services = services
        self.finished = False  # completed or handed on by the handler itself

    def store(self) -> AbstractContextManager[Store]:
        """A unit of work: ``with ctx.store() as store: …`` — committed when the block ends."""
        return self._services.stores()

    def progress(self, store: Store | None = None) -> None:
        """Record progress (once per photo), so the reaper does not take a long job for stuck.
        Pass the open unit of work to touch inside it."""
        if store is not None:
            store.jobs.touch(self.job_id)
            return
        with self.store() as s:
            s.jobs.touch(self.job_id)

    def complete(self, store: Store) -> None:
        """Mark the job COMPLETED inside the handler's unit of work (with its last writes)."""
        store.jobs.set_status(self.job_id, JobStatus.COMPLETED)
        self.finished = True

    def forward_to_inference(self) -> None:
        """Hand the edit job on to the inference queue; it stays RUNNING there."""
        self._services.publisher.forward_to_inference(self.envelope)
        self.finished = True


Handler = Callable[[JobContext[Any]], None]
# Extra writes when a job fails, in the same unit of work (e.g. the train worker's profile).
OnFailure = Callable[[JobContext[Any], Store, str], None]


@dataclass(frozen=True)
class Worker(Generic[P]):
    """One worker: ``name`` gives the logger ``calotype.<name>_worker`` and the heartbeat file."""

    name: str
    queue: str
    kind: str
    payload_model: type[P]
    handler: Handler
    # Job kinds whose pipeline starts on this queue: the reaper re-queues their stuck jobs here.
    reaper_kinds: tuple[str, ...] = ()
    on_failure: OnFailure | None = None
    # Only the workers that compute feature vectors need it (keeps inference-pipeline out of here).
    compute_features: ComputeFeatures | None = None

    @property
    def log(self) -> logging.Logger:
        return get_logger(f"calotype.{self.name}_worker")

    @property
    def heartbeat_path(self) -> str:
        return f"/tmp/lr_ff_{self.name}_worker.heartbeat"


def failure_reason(exc: BaseException) -> str:
    """The short, user-facing reason a failed job gets (the traceback goes to the log)."""
    return f"{type(exc).__name__}: {exc}"[:MAX_REASON_LENGTH]


def process_one(worker: Worker[Any], services: Services) -> bool:
    """Take one message from the worker's queue and run it; False when the queue was empty."""
    log = worker.log
    redis, queue = services.redis, worker.queue
    envelope, raw = consumer.blpop_envelope(redis, queue, timeout_seconds=BLPOP_TIMEOUT_SECONDS)
    if envelope is None and raw is None:
        return False
    if envelope is None:
        consumer.push_dead_letter(redis, primary_queue_name=queue, raw_payload=raw, reason="invalid_envelope")
        log.warning("dead-letter: invalid envelope")
        return True
    if envelope.job_kind != worker.kind:
        consumer.push_dead_letter(redis, primary_queue_name=queue, raw_payload=raw or "",
                                  reason=f"unexpected_job_kind:{envelope.job_kind}")
        log.warning("wrong kind on %s queue job_kind=%s", worker.name, envelope.job_kind)
        return True
    try:
        payload = worker.payload_model.model_validate(envelope.payload)
    except ValidationError:
        consumer.push_dead_letter(redis, primary_queue_name=queue, raw_payload=raw or "", reason="invalid_payload")
        log.warning("dead-letter: invalid payload job_id=%s", envelope.job_id)
        return True

    job_id = UUID(envelope.job_id)
    set_request_id(envelope.trace_context.get("request_id", ""))
    ctx: JobContext[Any] = JobContext(
        job_id=job_id, envelope=envelope, payload=payload, services=services,
        features=FeatureStore(services.blobs, worker.compute_features, log), log=log,
    )
    try:
        with services.stores() as store:
            store.jobs.set_status(job_id, JobStatus.RUNNING)
        worker.handler(ctx)
        if not ctx.finished:
            with services.stores() as store:
                store.jobs.set_status(job_id, JobStatus.COMPLETED)
    except Exception as exc:
        reason = failure_reason(exc)
        with services.stores() as store:
            store.jobs.set_status(job_id, JobStatus.FAILED, failure_reason=reason,
                                  failure_code=failure_code(exc))
            if worker.on_failure is not None:
                worker.on_failure(ctx, store, reason)
        if raw is not None:
            consumer.push_dead_letter(redis, primary_queue_name=queue, raw_payload=raw, reason="processing_error")
        log.exception("%s worker failure job_id=%s", worker.name, job_id)
    return True


def run_worker(worker: Worker[Any], services: Services | None = None) -> None:
    """The worker process: heartbeat, reaper, then `process_one` until stopped."""
    configure_logging()
    log = worker.log
    log.info("Calotype %s worker — queue %s", worker.name, worker.queue)
    services = services or Services.from_env()
    start_heartbeat_thread(worker.heartbeat_path)

    if worker.reaper_kinds:
        kinds = list(worker.reaper_kinds)
        n = reap_stuck_jobs(services.stores, queue_name=worker.queue, publisher=services.publisher, kinds=kinds)
        if n:
            log.warning("reaper: recovered %d stuck jobs at startup", n)
        start_reaper_thread(services.stores, queue_name=worker.queue, publisher=services.publisher,
                            kinds=kinds, logger=log)

    while True:
        try:
            if not process_one(worker, services):
                time.sleep(IDLE_SLEEP_SECONDS)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            # Redis restarted or the network hiccupped: keep the worker alive and retry.
            log.warning("redis unavailable, retrying in %ds: %s", REDIS_RETRY_SECONDS, exc)
            time.sleep(REDIS_RETRY_SECONDS)
        except KeyboardInterrupt:
            print(f"Stopping {worker.name} worker", file=sys.stderr)
            raise SystemExit(0) from None
