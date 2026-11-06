"""FastAPI entrypoint — persist jobs and enqueue envelopes (no heavy work here)."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from botocore.client import BaseClient
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from lr_frameflow_api.deps import get_publisher, get_session, get_storage
from lr_frameflow_api.middleware import RateLimitMiddleware, RequestIdMiddleware
from lr_frameflow_observability import configure_logging, get_request_id
from lr_frameflow_queue.publisher import QueueFullError, redis_from_env
from lr_frameflow_api.schemas import (
    EditJobRequestV1,
    EditResultResponse,
    JobAcceptedResponse,
    JobSnapshotResponse,
    PhotoCreatedResponse,
    PhotoMetadataV1,
    ProfileResponse,
    TrainJobRequestV1,
)
from lr_frameflow_api.storage import upload_photo
from lr_frameflow_domain.jobs import JobKind
from lr_frameflow_domain.profiles import ProfileStatus
from lr_frameflow_persistence.repositories.edit_results import EditResultRepository
from lr_frameflow_persistence.repositories.jobs import JobRepository
from lr_frameflow_persistence.repositories.photos import PhotoRepository
from lr_frameflow_persistence.repositories.profiles import ProfileRepository
from lr_frameflow_queue.envelope import JobEnvelopeV1
from lr_frameflow_queue.publisher import RedisQueuePublisher

configure_logging()

app = FastAPI(title="LR-FrameFlow API", version="0.1.1")
app.state.redis = redis_from_env()
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/photos", response_model=PhotoCreatedResponse)
async def upload_photo_endpoint(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    session: Session = Depends(get_session),
    storage: BaseClient = Depends(get_storage),
):
    try:
        meta = PhotoMetadataV1.model_validate(json.loads(metadata))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid metadata: {exc}") from exc

    existing = PhotoRepository.get_by_lr_catalog_uuid(session, meta.lr_catalog_uuid)
    if existing:
        # Same photo again: keep the stored preview, take the current edits and decisions
        # (the photographer may have re-edited or re-rated it since the first upload).
        PhotoRepository.refresh(
            session,
            existing,
            exif_snapshot=meta.exif_snapshot,
            lr_develop_settings=meta.lr_develop_settings,
            lr_metadata=meta.lr_metadata,
        )
        return PhotoCreatedResponse(
            photo_id=existing.id,
            s3_key=existing.s3_key,
            already_existed=True,
        )

    photo_id = uuid4()
    s3_key = f"photos/{photo_id}.jpg"
    image_data = await file.read()
    upload_photo(storage, s3_key, image_data)

    PhotoRepository.create(
        session,
        photo_id=photo_id,
        lr_catalog_uuid=meta.lr_catalog_uuid,
        s3_key=s3_key,
        exif_snapshot=meta.exif_snapshot,
        lr_develop_settings=meta.lr_develop_settings,
        lr_metadata=meta.lr_metadata,
    )
    return PhotoCreatedResponse(photo_id=photo_id, s3_key=s3_key, already_existed=False)


@app.get("/v1/profiles", response_model=list[ProfileResponse])
def list_profiles(session: Session = Depends(get_session)):
    profiles = ProfileRepository.list_all(session)
    return [
        ProfileResponse(
            profile_id=p.id,
            name=p.name,
            genre=p.genre,
            format_type=p.format_type,
            color_type=p.color_type,
            status=p.status,
            version=p.version,
            model_artifact_key=p.model_artifact_key,
            failure_reason=p.failure_reason,
        )
        for p in profiles
    ]


@app.get("/v1/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: UUID, session: Session = Depends(get_session)):
    profile = ProfileRepository.get_by_id(session, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return ProfileResponse(
        profile_id=profile.id,
        name=profile.name,
        genre=profile.genre,
        format_type=profile.format_type,
        color_type=profile.color_type,
        status=profile.status,
        version=profile.version,
        model_artifact_key=profile.model_artifact_key,
        failure_reason=profile.failure_reason,
    )


@app.post("/v1/jobs/train", status_code=202, response_model=JobAcceptedResponse)
def create_train_job(
    body: TrainJobRequestV1,
    session: Session = Depends(get_session),
    publisher: RedisQueuePublisher = Depends(get_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    norm_key = (idempotency_key or "").strip() or None
    if norm_key:
        existing = JobRepository.get_by_idempotency_key(session, norm_key)
        if existing:
            if existing.kind != JobKind.TRAIN.value:
                raise HTTPException(status_code=409, detail="idempotency key conflicts with another job kind")
            return JobAcceptedResponse(job_id=existing.id, kind="train", profile_id=existing.profile_id)

    # Create Profile record in DRAFT status.
    profile_id = uuid4()
    ProfileRepository.create(
        session,
        profile_id=profile_id,
        name=body.profile_name,
        genre=body.genre,
        format_type=body.format_type,
        color_type=body.color_type,
        base_preset=body.base_preset,
    )

    job_id = uuid4()
    payload = body.model_dump(mode="json")
    payload["profile_id"] = str(profile_id)
    JobRepository.create(
        session,
        job_id=job_id,
        kind=JobKind.TRAIN,
        payload_schema_version=body.schema_version,
        payload=payload,
        correlation_id=body.correlation_id,
        idempotency_key=norm_key,
        profile_id=profile_id,
    )

    trace: dict = {"request_id": get_request_id()}
    if body.correlation_id:
        trace["correlation_id"] = body.correlation_id
    envelope = JobEnvelopeV1(
        job_id=str(job_id),
        job_kind="train",
        payload=payload,
        trace_context=trace,
    )
    try:
        publisher.enqueue(envelope)
    except QueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return JobAcceptedResponse(job_id=job_id, kind="train", profile_id=profile_id)


@app.post("/v1/jobs/edit", status_code=202, response_model=JobAcceptedResponse)
def create_edit_job(
    body: EditJobRequestV1,
    session: Session = Depends(get_session),
    publisher: RedisQueuePublisher = Depends(get_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    norm_key = (idempotency_key or "").strip() or None
    if norm_key:
        existing = JobRepository.get_by_idempotency_key(session, norm_key)
        if existing:
            if existing.kind != JobKind.EDIT.value:
                raise HTTPException(status_code=409, detail="idempotency key conflicts with another job kind")
            return JobAcceptedResponse(job_id=existing.id, kind="edit")

    # Validate profile exists and is ready.
    profile = ProfileRepository.get_by_id(session, body.profile_id)
    if profile is None:
        raise HTTPException(status_code=422, detail="profile not found")
    if profile.status != ProfileStatus.READY.value:
        raise HTTPException(
            status_code=422,
            detail=f"profile is not ready (current status: {profile.status})",
        )

    # Validate all photo_ids exist.
    missing = [
        str(pid)
        for pid in body.photo_ids
        if PhotoRepository.get_by_id(session, pid) is None
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"unknown photo_ids: {missing}")

    job_id = uuid4()
    JobRepository.create(
        session,
        job_id=job_id,
        kind=JobKind.EDIT,
        payload_schema_version=body.schema_version,
        payload=body.model_dump(mode="json"),
        correlation_id=body.correlation_id,
        idempotency_key=norm_key,
        profile_id=body.profile_id,
    )

    trace: dict = {"request_id": get_request_id()}
    if body.correlation_id:
        trace["correlation_id"] = body.correlation_id
    envelope = JobEnvelopeV1(
        job_id=str(job_id),
        job_kind="edit",
        payload=body.model_dump(mode="json"),
        trace_context=trace,
    )
    try:
        publisher.enqueue(envelope)
    except QueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return JobAcceptedResponse(job_id=job_id, kind="edit")


@app.get("/v1/jobs/{job_id}", response_model=JobSnapshotResponse)
def get_job(job_id: UUID, session: Session = Depends(get_session)):
    record = JobRepository.get_by_id(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobSnapshotResponse(
        job_id=record.id,
        status=record.status,  # type: ignore[arg-type]
        payload_schema_version=record.payload_schema_version,
        profile_id=record.profile_id,
        failure_reason=record.failure_reason,
        correlation_id=record.correlation_id,
    )


@app.get("/v1/jobs/{job_id}/result", response_model=list[EditResultResponse])
def get_job_result(job_id: UUID, session: Session = Depends(get_session)):
    record = JobRepository.get_by_id(session, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if record.status != "completed":
        raise HTTPException(status_code=409, detail=f"job not yet completed (status: {record.status})")

    results = EditResultRepository.get_all_by_job_id(session, job_id)
    if not results:
        raise HTTPException(status_code=404, detail="no results found for this job")
    return [
        EditResultResponse(
            job_id=r.job_id,
            photo_id=r.photo_id,
            lr_settings=r.lr_settings,
            s3_key=r.s3_key,
        )
        for r in results
    ]
