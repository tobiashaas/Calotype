from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from calotype_domain import JobKind, JobStatus
from calotype_persistence.models import Job
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class JobRepository:
    @staticmethod
    def get_by_id(session: Session, job_id: uuid.UUID) -> Job | None:
        return session.get(Job, job_id)

    @staticmethod
    def get_by_idempotency_key(session: Session, key: str) -> Job | None:
        stmt = select(Job).where(Job.idempotency_key == key)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create(
        session: Session,
        *,
        job_id: uuid.UUID,
        kind: JobKind,
        payload_schema_version: str,
        payload: dict[str, Any],
        correlation_id: str | None,
        idempotency_key: str | None,
        profile_id: uuid.UUID | None = None,
    ) -> Job:
        job = Job(
            id=job_id,
            kind=kind.value,
            status=JobStatus.QUEUED.value,
            payload_schema_version=payload_schema_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload=payload,
            profile_id=profile_id,
        )
        session.add(job)
        session.flush()
        return job

    @staticmethod
    def set_status(
        session: Session,
        job_id: uuid.UUID,
        status: JobStatus,
        *,
        failure_reason: str | None = None,
    ) -> Job | None:
        job = session.get(Job, job_id)
        if job is None:
            return None
        job.sync_status_enum(status)
        job.failure_reason = failure_reason
        if status == JobStatus.RUNNING:
            job.started_at = job.last_progress_at = datetime.now(timezone.utc)
        session.flush()
        return job

    @staticmethod
    def find_stuck(
        session: Session, older_than: datetime, kinds: list[str] | None = None
    ) -> list[Job]:
        """RUNNING jobs without progress since before `older_than` (optionally of some kinds).

        Progress = the last `touch` (once per photo), else the start. A long job that still
        works is not stuck (found when 100-photo edit jobs behind a busy queue were re-run
        three times and returned every result three times).
        """
        stmt = select(Job).where(
            Job.status == JobStatus.RUNNING.value,
            func.coalesce(Job.last_progress_at, Job.started_at) <= older_than,
        )
        if kinds is not None:
            stmt = stmt.where(Job.kind.in_(kinds))
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def touch(session: Session, job_id: uuid.UUID) -> None:
        """Record progress of a running job (call once per processed photo)."""
        job = session.get(Job, job_id)
        if job is not None:
            job.last_progress_at = datetime.now(timezone.utc)
            session.flush()

    @staticmethod
    def reset_to_queued(session: Session, job_id: uuid.UUID) -> Job | None:
        job = session.get(Job, job_id)
        if job is None:
            return None
        job.sync_status_enum(JobStatus.QUEUED)
        job.started_at = None
        job.failure_reason = None
        session.flush()
        return job
