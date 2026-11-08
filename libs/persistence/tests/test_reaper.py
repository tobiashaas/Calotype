"""Stuck-job detection: progress counts, and each job kind has one owner (no DB needed)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from tarsier_persistence import reaper
from tarsier_persistence.models import EditResult, Job
from tarsier_persistence.repositories.edit_results import EditResultRepository
from tarsier_persistence.repositories.jobs import JobRepository


class CaptureSession:
    def __init__(self, objects=None):
        self.statements = []
        self.objects = objects or {}

    def execute(self, stmt):
        self.statements.append(stmt)

        class Result:
            def scalars(self):
                return self

            def all(self):
                return []

        return Result()

    def get(self, _model, key):
        return self.objects.get(key)

    def flush(self):
        pass


def sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect())).lower()


def test_stuck_means_no_progress_and_is_filtered_by_kind():
    session = CaptureSession()
    JobRepository.find_stuck(session, datetime.now(timezone.utc), kinds=["edit"])
    text = sql(session.statements[0])
    assert "coalesce(jobs.last_progress_at, jobs.started_at)" in text
    assert "jobs.kind in" in text


def test_touch_records_progress():
    job = Job(id=uuid.uuid4(), kind="edit", status="running", payload_schema_version="v1", payload={})
    session = CaptureSession({job.id: job})
    JobRepository.touch(session, job.id)
    assert job.last_progress_at is not None


def test_reaper_only_takes_its_own_kinds(monkeypatch):
    seen = {}

    def fake_find_stuck(_session, older_than, kinds=None):
        seen["kinds"] = kinds
        return []

    class FakeScope:
        def __enter__(self):
            return CaptureSession()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(reaper.JobRepository, "find_stuck", staticmethod(fake_find_stuck))
    monkeypatch.setattr(reaper, "session_scope", lambda _factory: FakeScope())
    assert reaper.reap_stuck_jobs(None, queue_name="q", publisher=None, kinds=["train"]) == 0
    assert seen["kinds"] == ["train"]


def test_edit_result_rerun_replaces_instead_of_adding():
    session = CaptureSession()
    ids = dict(job_id=uuid.uuid4(), photo_id=uuid.uuid4(), profile_id=uuid.uuid4())
    EditResultRepository.upsert(session, result_id=uuid.uuid4(), lr_settings={"Exposure2012": 0.3}, **ids)
    text = sql(session.statements[0])
    assert "on conflict on constraint uq_edit_results_job_photo do update" in text
    names = {c.name for c in EditResult.__table__.constraints}
    assert "uq_edit_results_job_photo" in names
