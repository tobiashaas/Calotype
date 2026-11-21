from __future__ import annotations

from redis import Redis

from calotype_queue.constants import dlq_name
from calotype_queue.envelope import dumps_dlq_item, JobEnvelopeV1


def blpop_raw(client: Redis, queue: str, *, timeout_seconds: int) -> str | None:
    out = client.blpop(queue, timeout_seconds)
    if out is None:
        return None
    _queue, payload = out
    return payload


def blpop_envelope(client: Redis, queue: str, *, timeout_seconds: int) -> tuple[JobEnvelopeV1 | None, str | None]:
    raw = blpop_raw(client, queue, timeout_seconds=timeout_seconds)
    if raw is None:
        return None, None
    try:
        return JobEnvelopeV1.loads(raw), raw
    except Exception:
        return None, raw


def push_dead_letter(
    client: Redis,
    *,
    primary_queue_name: str,
    raw_payload: str,
    reason: str,
) -> None:
    dlq_key = dlq_name(primary_queue_name)
    client.rpush(dlq_key, dumps_dlq_item(envelope_raw=raw_payload, reason=reason))
