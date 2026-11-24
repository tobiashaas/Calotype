"""Store contract: the same assertions against every `Store` adapter.

`memory` always runs. `postgres` runs only when `CALOTYPE_TEST_DATABASE_URL` points at a
migrated (`alembic upgrade head`) throwaway database; it commits for real (the order of a
profile's jobs is the order of their transactions) and deletes the rows it created afterwards.
Never point it at a database with photos you care about.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from calotype_domain.jobs import JobKind, JobStatus
from calotype_domain.profiles import ProfileStatus
from calotype_persistence.memory import MemoryStore
from calotype_persistence.stores import Store

_PG_URL = os.environ.get("CALOTYPE_TEST_DATABASE_URL")


@dataclass
class Harness:
    store: Store
    commit: Callable[[], None] = lambda: None
    ids: set[uuid.UUID] = field(default_factory=set)

    def new_id(self) -> uuid.UUID:
        value = uuid.uuid4()
        self.ids.add(value)
        return value

    # Small builders so each test states only what it is about.
    def photo(self, **overrides):
        fields = dict(photo_id=self.new_id(), lr_catalog_uuid=f"lr-{uuid.uuid4()}",
                      s3_key="photos/p.jpg", exif_snapshot={"iso": 100},
                      lr_develop_settings={"Exposure2012": 0.3})
        return self.store.photos.create(**{**fields, **overrides})

    def profile(self, **overrides):
        fields = dict(profile_id=self.new_id(), name="Golden Hour", genre="wedding", format_type="raw",
                      color_type="color", base_preset=None)
        return self.store.profiles.create(**{**fields, **overrides})

    def job(self, kind: JobKind = JobKind.TRAIN, **overrides):
        fields = dict(job_id=self.new_id(), kind=kind, payload_schema_version="v1", payload={"a": 1},
                      correlation_id=None, idempotency_key=None)
        return self.store.jobs.create(**{**fields, **overrides})


def _memory() -> Iterator[Harness]:
    yield Harness(MemoryStore())


def _postgres() -> Iterator[Harness]:
    from sqlalchemy import create_engine, text

    from calotype_persistence.session import get_session_factory
    from calotype_persistence.stores import SqlStore

    engine = create_engine(_PG_URL, pool_pre_ping=True)
    session = get_session_factory(engine)()
    harness = Harness(SqlStore(session), commit=session.commit)
    try:
        yield harness
    finally:
        session.rollback()
        ids = list(harness.ids)
        for table, column in [("cull_results", "job_id"), ("edit_results", "job_id"), ("jobs", "id"),
                              ("photos", "id"), ("profiles", "id")]:
            session.execute(text(f"DELETE FROM {table} WHERE {column} = ANY(:ids)"), {"ids": ids})
        session.commit()
        session.close()
        engine.dispose()


@pytest.fixture(params=[
    "memory",
    pytest.param("postgres", marks=pytest.mark.skipif(
        not _PG_URL, reason="set CALOTYPE_TEST_DATABASE_URL to a migrated throwaway database")),
])
def h(request) -> Iterator[Harness]:
    yield from (_memory() if request.param == "memory" else _postgres())


# --- photos ----------------------------------------------------------------------------------


def test_photo_is_found_by_id_and_catalog_identity(h):
    photo = h.photo(lr_metadata={"rating": 4})
    h.commit()
    assert h.store.photos.get(photo.id).lr_catalog_uuid == photo.lr_catalog_uuid
    found = h.store.photos.get_by_lr_catalog_uuid(photo.lr_catalog_uuid)
    assert found.id == photo.id
    assert found.lr_metadata == {"rating": 4}
    assert found.lr_develop_settings == {"Exposure2012": 0.3}


def test_unknown_photo_is_none(h):
    assert h.store.photos.get(uuid.uuid4()) is None
    assert h.store.photos.get_by_lr_catalog_uuid("never-uploaded") is None


def test_photo_without_decisions_has_empty_metadata(h):
    assert h.photo().lr_metadata == {}


def test_refresh_takes_current_settings_and_keeps_the_preview(h):
    photo = h.photo()
    h.store.photos.refresh(photo, exif_snapshot={"iso": 200}, lr_develop_settings={"Exposure2012": 0.8},
                           lr_metadata={"rating": 5})
    h.commit()
    again = h.store.photos.get(photo.id)
    assert again.lr_develop_settings == {"Exposure2012": 0.8}
    assert again.lr_metadata == {"rating": 5}
    assert again.s3_key == "photos/p.jpg"


# --- profiles --------------------------------------------------------------------------------


def test_new_profile_is_an_untrained_draft(h):
    profile = h.profile(base_preset={"GrainAmount": 25})
    h.commit()
    got = h.store.profiles.get(profile.id)
    assert (got.status, got.version, got.model_artifact_key, got.retouch, got.failure_reason) == (
        "draft", 1, None, None, None)
    assert got.base_preset == {"GrainAmount": 25}


def test_profiles_are_listed_newest_first(h):
    older = h.profile(name="older")
    h.commit()
    newer = h.profile(name="newer")
    h.commit()
    listed = [p.id for p in h.store.profiles.list_all() if p.id in {older.id, newer.id}]
    assert listed == [newer.id, older.id]


def test_unknown_profile_is_none(h):
    assert h.store.profiles.get(uuid.uuid4()) is None


# --- jobs ------------------------------------------------------------------------------------


def test_new_job_is_queued_with_its_payload(h):
    job = h.job(JobKind.EDIT, payload={"photo_ids": ["x"]}, correlation_id="c-1")
    h.commit()
    got = h.store.jobs.get(job.id)
    assert (got.kind, got.status, got.failure_reason, got.failure_code, got.correlation_id) == (
        "edit", "queued", None, None, "c-1")
    assert got.payload == {"photo_ids": ["x"]}


def test_job_is_found_by_idempotency_key(h):
    key = f"idem-{uuid.uuid4()}"
    job = h.job(idempotency_key=key)
    h.commit()
    assert h.store.jobs.get_by_idempotency_key(key).id == job.id
    assert h.store.jobs.get_by_idempotency_key(f"idem-{uuid.uuid4()}") is None


def test_a_profiles_jobs_of_one_kind_oldest_first(h):
    profile = h.profile()
    h.commit()
    first = h.job(JobKind.TRAIN, profile_id=profile.id)
    h.commit()
    h.job(JobKind.EDIT, profile_id=profile.id)
    h.job(JobKind.TRAIN)  # another profile's (none)
    h.commit()
    second = h.job(JobKind.TRAIN, profile_id=profile.id)
    h.commit()
    assert [j.id for j in h.store.jobs.list_for_profile(profile.id, JobKind.TRAIN)] == [first.id, second.id]


# --- results ---------------------------------------------------------------------------------


def test_edit_results_of_a_job_and_a_rerun_replaces(h):
    a, b = h.photo(), h.photo()
    job, other = h.job(JobKind.EDIT), h.job(JobKind.EDIT)
    h.commit()
    for lr_settings in ({"Exposure2012": 0.1}, {"Exposure2012": 0.5}):  # the job ran twice
        h.store.edit_results.upsert(result_id=h.new_id(), job_id=job.id, photo_id=a.id, profile_id=None,
                                    lr_settings=lr_settings, retouch={"subject_pop": {"LocalExposure2012": 0.2}})
    h.store.edit_results.upsert(result_id=h.new_id(), job_id=job.id, photo_id=b.id, profile_id=None,
                                lr_settings={"Exposure2012": -0.2})
    h.store.edit_results.upsert(result_id=h.new_id(), job_id=other.id, photo_id=a.id, profile_id=None,
                                lr_settings={})
    h.commit()
    results = {r.photo_id: r for r in h.store.edit_results.for_job(job.id)}
    assert set(results) == {a.id, b.id}
    assert results[a.id].lr_settings == {"Exposure2012": 0.5}
    assert results[a.id].retouch == {"subject_pop": {"LocalExposure2012": 0.2}}
    assert results[b.id].retouch is None
    assert h.store.edit_results.for_job(uuid.uuid4()) == []


def test_cull_results_of_a_job_and_a_rerun_replaces(h):
    photo = h.photo()
    job = h.job(JobKind.CULL)
    h.commit()
    h.store.cull_results.upsert(job_id=job.id, photo_id=photo.id, bucket="uncertain", score=0.5,
                                reason="soft", method="rules")
    h.store.cull_results.upsert(job_id=job.id, photo_id=photo.id, bucket="keep", score=0.9,
                                reason="sharp", method="learned")
    h.commit()
    [result] = h.store.cull_results.for_job(job.id)
    assert (result.photo_id, result.bucket, result.score, result.reason, result.method) == (
        photo.id, "keep", 0.9, "sharp", "learned")


def test_edit_result_keeps_the_photos_own_crop_flag(h):
    photo, job = h.photo(), h.job(JobKind.EDIT)
    h.commit()
    h.store.edit_results.upsert(result_id=h.new_id(), job_id=job.id, photo_id=photo.id, profile_id=None,
                                lr_settings={"CropAngle": 1.2}, kept_crop=True)
    h.commit()
    [result] = h.store.edit_results.for_job(job.id)
    assert result.kept_crop is True


# --- what the workers write ------------------------------------------------------------------


def test_job_lifecycle_running_progress_failed(h):
    job = h.job(JobKind.CULL)
    h.commit()
    running = h.store.jobs.set_status(job.id, JobStatus.RUNNING)
    h.commit()
    assert running.status == "running" and running.started_at is not None
    started = h.store.jobs.get(job.id).last_progress_at
    h.store.jobs.touch(job.id)
    h.commit()
    assert h.store.jobs.get(job.id).last_progress_at >= started
    h.store.jobs.set_status(job.id, JobStatus.FAILED, failure_reason="ValueError: no", failure_code="too_few_photos")
    h.commit()
    got = h.store.jobs.get(job.id)
    assert (got.status, got.failure_reason, got.failure_code) == ("failed", "ValueError: no", "too_few_photos")
    assert h.store.jobs.set_status(uuid.uuid4(), JobStatus.RUNNING) is None


def test_stuck_jobs_are_running_without_progress_of_the_given_kinds(h):
    edit, train, queued = h.job(JobKind.EDIT), h.job(JobKind.TRAIN), h.job(JobKind.EDIT)
    h.commit()
    for job in (edit, train):
        h.store.jobs.set_status(job.id, JobStatus.RUNNING)
    h.commit()
    later = datetime.now(timezone.utc) + timedelta(minutes=1)
    ours = {edit.id, train.id, queued.id}
    assert {j.id for j in h.store.jobs.find_stuck(later, ["edit"]) if j.id in ours} == {edit.id}
    assert {j.id for j in h.store.jobs.find_stuck(later) if j.id in ours} == {edit.id, train.id}
    earlier = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert [j for j in h.store.jobs.find_stuck(earlier) if j.id in ours] == []
    h.store.jobs.reset_to_queued(edit.id)
    h.commit()
    got = h.store.jobs.get(edit.id)
    assert (got.status, got.started_at, got.failure_reason) == ("queued", None, None)


def test_photo_analysis_is_merged_and_vector_linked(h):
    photo = h.photo()
    h.commit()
    h.store.photos.merge_analysis(photo.id, {"straighten": {"crop_angle": 0.5}})
    h.store.photos.merge_analysis(photo.id, {"cull": {"sharpness": 3.0}})
    vector_id = h.new_id()
    h.store.feature_vectors.create(vector_id=vector_id, photo_id=photo.id, model_version="v-test",
                                   vector=[0.25] * 8)
    h.store.photos.set_feature_vector_id(photo.id, vector_id)
    h.commit()
    got = h.store.photos.get(photo.id)
    assert got.analysis == {"straighten": {"crop_angle": 0.5}, "cull": {"sharpness": 3.0}}
    assert got.feature_vector_id == vector_id


def test_feature_vectors_per_photo_and_version(h):
    photo = h.photo()
    h.commit()
    h.store.feature_vectors.create(vector_id=h.new_id(), photo_id=photo.id, model_version="v-a",
                                   vector=[0.5] * 4)
    h.commit()
    assert list(h.store.feature_vectors.get(photo.id, "v-a").vector) == [0.5] * 4
    assert h.store.feature_vectors.get(photo.id, "v-b") is None
    assert h.store.feature_vectors.get(uuid.uuid4(), "v-a") is None


def test_profile_training_outcome(h):
    profile = h.profile()
    h.commit()
    h.store.profiles.set_status(profile.id, ProfileStatus.TRAINING)
    h.store.profiles.set_artifact(profile.id, model_artifact_key="models/x/model-v2.joblib", retouch={})
    h.store.profiles.set_status(profile.id, ProfileStatus.READY)
    h.commit()
    got = h.store.profiles.get(profile.id)
    assert (got.status, got.model_artifact_key, got.retouch, got.failure_reason) == (
        "ready", "models/x/model-v2.joblib", None, None)
    h.store.profiles.set_status(profile.id, ProfileStatus.FAILED, failure_reason="TooFewPhotosError: 2")
    h.store.profiles.set_artifact(profile.id, model_artifact_key="k", retouch={"subject": {"LocalShadows2012": 0.2}})
    h.commit()
    got = h.store.profiles.get(profile.id)
    assert (got.status, got.failure_reason, got.retouch) == (
        "failed", "TooFewPhotosError: 2", {"subject": {"LocalShadows2012": 0.2}})
