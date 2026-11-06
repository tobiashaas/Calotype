from __future__ import annotations

import os

from redis import Redis

from lr_frameflow_domain.jobs import JobKind
from lr_frameflow_queue.constants import QUEUE_FEATURE, QUEUE_INFERENCE, QUEUE_TRAIN
from lr_frameflow_queue.envelope import JobEnvelopeV1

# Maximum number of messages allowed in a queue before enqueue is refused.
# Override via env var MAX_QUEUE_DEPTH (per queue).
DEFAULT_MAX_QUEUE_DEPTH = int(os.environ.get("MAX_QUEUE_DEPTH", "500"))


class QueueFullError(Exception):
    """Raised when a queue has reached its maximum depth."""


# Workers block in BLPOP for up to 5 s. The socket read timeout must be clearly longer,
# otherwise an empty queue raises TimeoutError (newer redis-py versions set a default).
SOCKET_TIMEOUT_SECONDS = 30


def redis_from_env(default_url: str = "redis://127.0.0.1:6379/0") -> Redis:
    return Redis.from_url(
        os.environ.get("REDIS_URL", default_url),
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )


def first_stage_queue(kind: JobKind) -> str:
    if kind == JobKind.TRAIN:
        return QUEUE_TRAIN
    if kind == JobKind.EDIT:
        return QUEUE_FEATURE
    raise ValueError(kind)


class RedisQueuePublisher:
    def __init__(self, client: Redis) -> None:
        self._r = client

    def queue_depth(self, queue_name: str) -> int:
        return int(self._r.llen(queue_name))

    def enqueue(self, envelope: JobEnvelopeV1, *, max_depth: int = DEFAULT_MAX_QUEUE_DEPTH) -> None:
        kind = JobKind(envelope.job_kind)
        q = first_stage_queue(kind)
        if self.queue_depth(q) >= max_depth:
            raise QueueFullError(f"queue {q!r} is at capacity ({max_depth} messages)")
        self._r.rpush(q, envelope.dumps())

    def enqueue_to(self, queue: str, envelope: JobEnvelopeV1) -> None:
        """Push an envelope onto an explicit queue (used by the reaper)."""
        self._r.rpush(queue, envelope.dumps())

    def forward_to_inference(self, envelope: JobEnvelopeV1) -> None:
        nxt = envelope.model_copy(update={"attempt": envelope.attempt + 1})
        self._r.rpush(QUEUE_INFERENCE, nxt.dumps())
