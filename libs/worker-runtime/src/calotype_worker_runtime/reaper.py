"""Stuck-job reaper — RUNNING jobs without progress go back to QUEUED and onto their queue.

Each job kind has exactly one owner: the worker whose queue starts its pipeline (edit →
feature, train → train, cull → cull); `Worker.reaper_kinds` says which. Without that filter
every worker re-enqueued every stuck job onto its own queue, e.g. an edit job onto the train
queue. Progress = the last `touch` (once per photo), else the start: a long job that still
works is not stuck.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from calotype_queue.envelope import JobEnvelopeV1

if TYPE_CHECKING:
    from calotype_queue.publisher import RedisQueuePublisher

    from calotype_worker_runtime.runner import Stores

# Jobs stuck in RUNNING for longer than this are eligible for recovery.
STUCK_TIMEOUT_MINUTES = 10


def reap_stuck_jobs(
    stores: Stores,
    *,
    queue_name: str,
    publisher: RedisQueuePublisher,
    kinds: list[str],
    timeout_minutes: int = STUCK_TIMEOUT_MINUTES,
) -> int:
    """Reset stuck jobs of ``kinds`` and re-enqueue them onto ``queue_name``; returns how many."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    recovered = 0
    with stores() as store:
        for job in store.jobs.find_stuck(cutoff, kinds):
            store.jobs.reset_to_queued(job.id)
            envelope = JobEnvelopeV1(job_id=str(job.id), job_kind=job.kind, payload=job.payload,
                                     trace_context={})
            publisher.enqueue_to(queue_name, envelope)
            recovered += 1
    return recovered


def start_reaper_thread(
    stores: Stores,
    *,
    queue_name: str,
    publisher: RedisQueuePublisher,
    kinds: list[str],
    interval_seconds: int = 60,
    timeout_minutes: int = STUCK_TIMEOUT_MINUTES,
    logger: logging.Logger | None = None,
) -> threading.Thread:
    """A daemon thread that runs `reap_stuck_jobs` every ``interval_seconds``."""

    def _loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                n = reap_stuck_jobs(stores, queue_name=queue_name, publisher=publisher, kinds=kinds,
                                    timeout_minutes=timeout_minutes)
                if n and logger:
                    logger.warning("reaper: recovered %d stuck jobs on queue %s", n, queue_name)
            except Exception:
                if logger:
                    logger.exception("reaper: error during stuck-job sweep")

    t = threading.Thread(target=_loop, daemon=True, name=f"reaper-{queue_name}")
    t.start()
    return t
