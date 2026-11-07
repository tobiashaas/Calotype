"""Stuck-job reaper — resets RUNNING jobs that have timed out back to QUEUED.

Usage (call once at worker startup, then periodically in a background thread):

    from lr_frameflow_persistence.reaper import reap_stuck_jobs
    reap_stuck_jobs(factory, queue_name=QUEUE_FEATURE, publisher=publisher, kinds=["edit"])
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from lr_frameflow_persistence.repositories.jobs import JobRepository
from lr_frameflow_persistence.session import session_scope

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from lr_frameflow_queue.publisher import RedisQueuePublisher

# Jobs stuck in RUNNING for longer than this are eligible for recovery.
STUCK_TIMEOUT_MINUTES = 10


def reap_stuck_jobs(
    factory: sessionmaker,
    *,
    queue_name: str,
    publisher: RedisQueuePublisher,
    kinds: list[str],
    timeout_minutes: int = STUCK_TIMEOUT_MINUTES,
) -> int:
    """Reset stuck jobs of `kinds` and re-enqueue them onto `queue_name`.

    Each kind needs exactly one owner: the queue where its pipeline starts (edit → feature,
    train → train). Without the filter every worker re-enqueued every stuck job onto its own
    queue, e.g. an edit job onto the train queue.

    Returns the number of jobs recovered.
    """
    from lr_frameflow_queue.envelope import JobEnvelopeV1

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

    recovered = 0
    with session_scope(factory) as session:
        stuck = JobRepository.find_stuck(session, older_than=cutoff, kinds=kinds)
        for job in stuck:
            JobRepository.reset_to_queued(session, job.id)
            # Re-enqueue onto the exact queue this worker owns so it picks it up again.
            envelope = JobEnvelopeV1(
                job_id=str(job.id),
                job_kind=job.kind,
                payload=job.payload,
                trace_context={},
            )
            publisher.enqueue_to(queue_name, envelope)
            recovered += 1

    return recovered


def start_reaper_thread(
    factory: sessionmaker,
    *,
    queue_name: str,
    publisher: RedisQueuePublisher,
    kinds: list[str],
    interval_seconds: int = 60,
    timeout_minutes: int = STUCK_TIMEOUT_MINUTES,
    logger=None,
) -> threading.Thread:
    """Start a daemon thread that runs reap_stuck_jobs every `interval_seconds`.

    The thread is a daemon so it exits automatically when the main process ends.
    """

    def _loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                n = reap_stuck_jobs(
                    factory,
                    queue_name=queue_name,
                    publisher=publisher,
                    kinds=kinds,
                    timeout_minutes=timeout_minutes,
                )
                if n and logger:
                    logger.warning("reaper: recovered %d stuck jobs on queue %s", n, queue_name)
            except Exception:
                if logger:
                    logger.exception("reaper: error during stuck-job sweep")

    t = threading.Thread(target=_loop, daemon=True, name=f"reaper-{queue_name}")
    t.start()
    return t
