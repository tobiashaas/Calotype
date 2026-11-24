"""FastAPI entrypoint — persist jobs and enqueue envelopes (no heavy work here)."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile

from calotype_api.deps import get_publisher, get_storage, get_store
from calotype_api.middleware import RateLimitMiddleware, RequestIdMiddleware
from calotype_observability import configure_logging, get_request_id
from calotype_queue.publisher import QueueFullError, redis_from_env
from calotype_api.schemas import (
    CullJobRequestV1,
    CullResultResponse,
    EditJobRequestV1,
    EditResultResponse,
    JobAcceptedResponse,
    JobSnapshotResponse,
    PhotoCreatedResponse,
    PhotoMetadataV1,
    ProfileResponse,
    ProfileUpdateV1,
    TrainJobRequestV1,
)
from calotype_api.training import merged_training
from calotype_domain.jobs import JobKind
from calotype_domain.profiles import ProfileStatus
from calotype_io import BlobStore
from calotype_persistence.models import Profile
from calotype_persistence.stores import Store
from calotype_queue.envelope import JobEnvelopeV1
from calotype_queue.payloads import TrainPayloadV1
from calotype_queue.publisher import RedisQueuePublisher

configure_logging()

app = FastAPI(title="Calotype API", version="0.1.1")
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
    store: Store = Depends(get_store),
    storage: BlobStore = Depends(get_storage),
):
    try:
        meta = PhotoMetadataV1.model_validate(json.loads(metadata))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid metadata: {exc}") from exc

    existing = store.photos.get_by_lr_catalog_uuid(meta.lr_catalog_uuid)
    if existing:
        # Same photo again: keep the stored preview, take the current edits and decisions
        # (the photographer may have re-edited or re-rated it since the first upload).
        store.photos.refresh(
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
    image_data = await file.read()
    s3_key = storage.put_preview(photo_id, image_data)

    store.photos.create(
        photo_id=photo_id,
        lr_catalog_uuid=meta.lr_catalog_uuid,
        s3_key=s3_key,
        exif_snapshot=meta.exif_snapshot,
        lr_develop_settings=meta.lr_develop_settings,
        lr_metadata=meta.lr_metadata,
    )
    return PhotoCreatedResponse(photo_id=photo_id, s3_key=s3_key, already_existed=False)


def _profile_response(p: Profile) -> ProfileResponse:
    return ProfileResponse(
        profile_id=p.id,
        name=p.name,
        genre=p.genre,
        format_type=p.format_type,
        color_type=p.color_type,
        status=p.status,
        version=p.version,
        model_artifact_key=p.model_artifact_key,
        failure_reason=p.failure_reason,
        accepted_marker=p.accepted_marker,
    )


def _live_profile(store: Store, profile_id: UUID) -> Profile | None:
    """The profile, unless it does not exist or was deleted (deleted ones are only hidden)."""
    profile = store.profiles.get(profile_id)
    return profile if profile is not None and profile.deleted_at is None else None


@app.get("/v1/profiles", response_model=list[ProfileResponse])
def list_profiles(store: Store = Depends(get_store)):
    return [_profile_response(p) for p in store.profiles.list_all()]


@app.get("/v1/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: UUID, store: Store = Depends(get_store)):
    profile = _live_profile(store, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return _profile_response(profile)


@app.patch("/v1/profiles/{profile_id}", response_model=ProfileResponse)
def update_profile(profile_id: UUID, body: ProfileUpdateV1, store: Store = Depends(get_store)):
    """Rename a profile and/or change the photographer's marker for accepted photos."""
    profile = _live_profile(store, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be blank")
        store.profiles.rename(profile_id, name)
    if "accepted_marker" in body.model_fields_set:
        marker = body.accepted_marker.stored() if body.accepted_marker is not None else None
        store.profiles.set_accepted_marker(profile_id, marker)
    return _profile_response(store.profiles.get(profile_id))


@app.delete("/v1/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: UUID, store: Store = Depends(get_store)):
    """Soft delete: the profile disappears from the list, from apply and from retraining; its
    jobs, results and model artifacts stay. Deleting it again changes nothing."""
    if store.profiles.get(profile_id) is None:
        raise HTTPException(status_code=404, detail="profile not found")
    store.profiles.delete(profile_id)
    return Response(status_code=204)


@app.post("/v1/jobs/train", status_code=202, response_model=JobAcceptedResponse)
def create_train_job(
    body: TrainJobRequestV1,
    store: Store = Depends(get_store),
    publisher: RedisQueuePublisher = Depends(get_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    norm_key = (idempotency_key or "").strip() or None
    if norm_key:
        existing = store.jobs.get_by_idempotency_key(norm_key)
        if existing:
            if existing.kind != JobKind.TRAIN.value:
                raise HTTPException(status_code=409, detail="idempotency key conflicts with another job kind")
            return JobAcceptedResponse(job_id=existing.id, kind="train", profile_id=existing.profile_id)

    payload = TrainPayloadV1.model_validate(body.model_dump())
    # Accepted photos: the selection's photos carrying the photographer's marker, as server ids
    # (catalog uuids of photos not in the selection or never uploaded are ignored).
    selected = set(body.photo_ids)
    accepted = []
    for lr_uuid in body.accepted_lr_catalog_uuids or ():
        photo = store.photos.get_by_lr_catalog_uuid(lr_uuid)
        if photo is not None and photo.id in selected:
            accepted.append(photo.id)
    marker = body.accepted_marker.stored() if body.accepted_marker is not None else None
    if body.profile_id is not None:
        # Retrain: one profile that keeps learning from the photographer's corrections.
        profile = _live_profile(store, body.profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"profile {body.profile_id} not found")
        if profile.format_type != body.format_type:
            raise HTTPException(status_code=409, detail=f"profile {profile.id} is for {profile.format_type} photos")
        earlier = [job.payload for job in store.jobs.list_for_profile(profile.id, JobKind.TRAIN)]
        merged = merged_training(earlier, body.photo_ids, body.untouched, accepted)
        profile_id = profile.id
        if body.accepted_marker is not None:
            store.profiles.set_accepted_marker(profile_id, marker)
        payload = payload.model_copy(update={
            "photo_ids": merged.photo_ids, "untouched": merged.untouched, "accepted": merged.accepted,
            "retrain": profile.model_artifact_key is not None,
        })
    else:
        # Create Profile record in DRAFT status.
        profile_id = uuid4()
        store.profiles.create(
            profile_id=profile_id,
            name=body.profile_name,
            genre=body.genre,
            format_type=body.format_type,
            color_type=body.color_type,
            base_preset=body.base_preset,
            accepted_marker=marker,
        )
        payload = payload.model_copy(update={"accepted": accepted})
    payload = payload.model_copy(update={"profile_id": profile_id}).model_dump(mode="json")

    job_id = uuid4()
    store.jobs.create(
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
    store: Store = Depends(get_store),
    publisher: RedisQueuePublisher = Depends(get_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    norm_key = (idempotency_key or "").strip() or None
    if norm_key:
        existing = store.jobs.get_by_idempotency_key(norm_key)
        if existing:
            if existing.kind != JobKind.EDIT.value:
                raise HTTPException(status_code=409, detail="idempotency key conflicts with another job kind")
            return JobAcceptedResponse(job_id=existing.id, kind="edit")

    # Validate profile exists and is ready (without one, the look comes from the edits only).
    if body.profile_id is not None:
        profile = _live_profile(store, body.profile_id)
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
        if store.photos.get(pid) is None
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"unknown photo_ids: {missing}")

    job_id = uuid4()
    store.jobs.create(
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


@app.post("/v1/jobs/cull", status_code=202, response_model=JobAcceptedResponse)
def create_cull_job(
    body: CullJobRequestV1,
    store: Store = Depends(get_store),
    publisher: RedisQueuePublisher = Depends(get_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    norm_key = (idempotency_key or "").strip() or None
    if norm_key:
        existing = store.jobs.get_by_idempotency_key(norm_key)
        if existing:
            if existing.kind != JobKind.CULL.value:
                raise HTTPException(status_code=409, detail="idempotency key conflicts with another job kind")
            return JobAcceptedResponse(job_id=existing.id, kind="cull")

    missing = [str(pid) for pid in body.photo_ids if store.photos.get(pid) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"unknown photo_ids: {missing}")

    job_id = uuid4()
    store.jobs.create(
        job_id=job_id,
        kind=JobKind.CULL,
        payload_schema_version=body.schema_version,
        payload=body.model_dump(mode="json"),
        correlation_id=body.correlation_id,
        idempotency_key=norm_key,
    )
    trace: dict = {"request_id": get_request_id()}
    if body.correlation_id:
        trace["correlation_id"] = body.correlation_id
    envelope = JobEnvelopeV1(job_id=str(job_id), job_kind="cull", payload=body.model_dump(mode="json"),
                             trace_context=trace)
    try:
        publisher.enqueue(envelope)
    except QueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return JobAcceptedResponse(job_id=job_id, kind="cull")


@app.get("/v1/jobs/{job_id}/cull-result", response_model=list[CullResultResponse])
def get_cull_result(job_id: UUID, store: Store = Depends(get_store)):
    record = store.jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if record.kind != JobKind.CULL.value:
        raise HTTPException(status_code=409, detail="not a cull job")
    if record.status != "completed":
        raise HTTPException(status_code=409, detail=f"job not yet completed (status: {record.status})")
    return [
        CullResultResponse(job_id=r.job_id, photo_id=r.photo_id, bucket=r.bucket, score=r.score,
                           reason=r.reason, method=r.method)
        for r in store.cull_results.for_job(job_id)
    ]


@app.get("/v1/jobs/{job_id}", response_model=JobSnapshotResponse)
def get_job(job_id: UUID, store: Store = Depends(get_store)):
    record = store.jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobSnapshotResponse(
        job_id=record.id,
        status=record.status,  # type: ignore[arg-type]
        payload_schema_version=record.payload_schema_version,
        profile_id=record.profile_id,
        failure_reason=record.failure_reason,
        failure_code=record.failure_code,
        correlation_id=record.correlation_id,
    )


@app.get("/v1/jobs/{job_id}/result", response_model=list[EditResultResponse])
def get_job_result(job_id: UUID, store: Store = Depends(get_store)):
    record = store.jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if record.status != "completed":
        raise HTTPException(status_code=409, detail=f"job not yet completed (status: {record.status})")

    results = store.edit_results.for_job(job_id)
    if not results:
        raise HTTPException(status_code=404, detail="no results found for this job")
    return [
        EditResultResponse(
            job_id=r.job_id,
            photo_id=r.photo_id,
            lr_settings=r.lr_settings,
            s3_key=r.s3_key,
            retouch=r.retouch,
            kept_crop=r.kept_crop,
        )
        for r in results
    ]
