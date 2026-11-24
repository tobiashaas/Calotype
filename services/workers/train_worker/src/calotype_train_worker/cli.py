"""Training worker — trains a profile model from photo feature vectors."""

from __future__ import annotations

import os
import sys
import time
from uuid import UUID, uuid4

import boto3
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import ValidationError

from calotype_edit_serializer import shared_masks, training_target
from calotype_domain.jobs import JobStatus
from calotype_domain.failures import TooFewPhotosError, failure_code
from calotype_domain.profiles import ProfileStatus
from calotype_inference_pipeline import (
    CURRENT_FEATURE_VERSION,
    MIN_SAMPLES,
    compute_features,
    train_for_version,
)
from calotype_observability import configure_logging, get_logger, set_request_id, start_heartbeat_thread
from calotype_persistence.reaper import reap_stuck_jobs, start_reaper_thread
from calotype_persistence.repositories.feature_vectors import FeatureVectorRepository
from calotype_persistence.repositories.jobs import JobRepository
from calotype_persistence.repositories.photos import PhotoRepository
from calotype_persistence.repositories.profiles import ProfileRepository
from calotype_persistence.session import get_session_factory, session_scope
from calotype_queue import consumer
from calotype_queue.constants import QUEUE_TRAIN
from calotype_queue.payloads import TrainPayloadV1
from calotype_queue.publisher import RedisQueuePublisher, redis_from_env

log = get_logger("calotype.train_worker")




def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minio"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "miniosecret_changeme"),
        region_name="us-east-1",
    )


def _ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)


def _ensure_feature_vector(
    session: Session, s3, bucket: str, photo, version: str = CURRENT_FEATURE_VERSION
) -> list[float] | None:
    """Return the photo's feature vector, extracting and storing it if missing.

    Returns None when the preview cannot be downloaded or decoded — a zero vector
    would teach the model nonsense.
    """
    existing = FeatureVectorRepository.get_by_photo_id(session, photo.id, version)
    if existing is not None:
        return list(existing.vector)
    try:
        image_bytes = s3.get_object(Bucket=bucket, Key=photo.s3_key)["Body"].read()
    except Exception as exc:
        log.warning("could not download preview photo_id=%s: %s", photo.id, exc)
        return None
    try:
        vector = compute_features(image_bytes, version)
    except ValueError:
        vector = []
    if not any(vector):
        log.warning("preview not decodable photo_id=%s", photo.id)
        return None
    fv_id = uuid4()
    FeatureVectorRepository.create(
        session,
        vector_id=fv_id,
        photo_id=photo.id,
        model_version=version,
        vector=vector,
    )
    PhotoRepository.set_feature_vector_id(session, photo.id, fv_id)
    return vector


def process_one(redis: Redis, factory: sessionmaker) -> bool:
    envelope, raw = consumer.blpop_envelope(redis, QUEUE_TRAIN, timeout_seconds=5)
    if envelope is None and raw is None:
        return False
    if envelope is None:
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_TRAIN, raw_payload=raw, reason="invalid_envelope")
        return True

    if envelope.job_kind != "train":
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_TRAIN, raw_payload=raw or "", reason=f"unexpected_job_kind:{envelope.job_kind}")
        return True

    try:
        payload = TrainPayloadV1.model_validate(envelope.payload)
    except ValidationError:
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_TRAIN, raw_payload=raw or "", reason="invalid_payload")
        return True
    job_uuid = UUID(envelope.job_id)
    profile_id_str = str(payload.profile_id) if payload.profile_id else None
    photo_ids = payload.photo_ids
    # Values only a preset left (Lightroom key -> value): not the photographer's decision.
    untouched = payload.untouched or {}
    # Retraining a profile that already has a model: a failure must not take that model away.
    retrain = payload.retrain
    set_request_id(envelope.trace_context.get("request_id", ""))

    try:
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.RUNNING)
            if profile_id_str and not retrain:  # a retrained profile stays usable meanwhile
                ProfileRepository.set_status(session, UUID(profile_id_str), ProfileStatus.TRAINING)

        format_type = "raw"
        if profile_id_str:
            with session_scope(factory) as session:
                profile = ProfileRepository.get_by_id(session, UUID(profile_id_str))
                if profile is not None:
                    format_type = profile.format_type

        bucket = os.environ.get("S3_BUCKET", "calotype-photos")
        s3 = _s3_client()

        # Training rows: features of the preview + the user's LR settings as targets.
        # Features are computed here when missing — freshly uploaded photos have none yet.
        feature_vectors: list[list[float]] = []
        targets: list[dict[str, float]] = []
        as_shot: list[bool] = []
        used_settings: list[dict] = []
        skipped: list[str] = []
        for photo_id in photo_ids:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                photo = PhotoRepository.get_by_id(session, photo_id)
                if photo is None:
                    skipped.append(f"{photo_id}: not found")
                    continue
                target = training_target(photo.lr_develop_settings or {}, format_type, untouched)
                if not target.sliders:
                    skipped.append(f"{photo_id}: no slider the photographer decided")
                    continue
                vector = _ensure_feature_vector(session, s3, bucket, photo)
                if vector is None:
                    skipped.append(f"{photo_id}: preview unavailable")
                    continue
                feature_vectors.append(vector)
                targets.append(target.sliders)
                as_shot.append(target.as_shot)
                used_settings.append(dict(photo.lr_develop_settings or {}))

        if skipped:
            log.warning("skipped %d training photos: %s", len(skipped), "; ".join(skipped[:20]))
        if len(feature_vectors) < MIN_SAMPLES:
            raise TooFewPhotosError(
                f"only {len(feature_vectors)} usable training photos, need at least {MIN_SAMPLES}"
            )

        # Photos on the camera's white balance teach their Kelvin too; at apply time a photo
        # keeps the camera's white balance when the prediction is close to it (model.py).
        undecided = {k: sum(1 for t in targets if k not in t) for k in ("highlights", "exposure", "temp")}
        log.info("white balance: %d of %d training photos as shot; undecided values %s untouched=%s",
                 sum(as_shot), len(as_shot), undecided, untouched)
        model_bytes = train_for_version(feature_vectors, targets, CURRENT_FEATURE_VERSION, as_shot=as_shot)
        profile_id = UUID(profile_id_str) if profile_id_str else None
        artifact_name = f"model-{CURRENT_FEATURE_VERSION}.joblib"
        artifact_key = f"models/{profile_id}/{artifact_name}" if profile_id else f"models/job-{job_uuid}/{artifact_name}"
        _ensure_bucket(s3, bucket)
        s3.put_object(Bucket=bucket, Key=artifact_key, Body=model_bytes, ContentType="application/octet-stream")
        log.info("model artifact saved key=%s n_samples=%d", artifact_key, len(feature_vectors))

        # Update profile: artifact key + status ready
        with session_scope(factory) as session:
            if profile_id:
                # Mask strengths the training photos share (subject shadows, sky …).
                retouch = shared_masks(used_settings)
                log.info("learned mask strengths %s profile_id=%s", retouch, profile_id)
                ProfileRepository.set_artifact(session, profile_id, model_artifact_key=artifact_key,
                                               retouch=retouch)
                ProfileRepository.set_status(session, profile_id, ProfileStatus.READY)
            JobRepository.set_status(session, job_uuid, JobStatus.COMPLETED)

        log.info("train job completed job_id=%s profile_id=%s", job_uuid, profile_id)

    except Exception as exc:
        # Short, user-facing reason (shown in Lightroom); the traceback goes to the log.
        reason = f"{type(exc).__name__}: {exc}"[:500]
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.FAILED, failure_reason=reason,
                                     failure_code=failure_code(exc))
            if profile_id_str:
                # A retrained profile keeps its earlier model and stays usable.
                status = ProfileStatus.READY if retrain else ProfileStatus.FAILED
                ProfileRepository.set_status(session, UUID(profile_id_str), status, failure_reason=reason)
        if raw is not None:
            consumer.push_dead_letter(redis, primary_queue_name=QUEUE_TRAIN, raw_payload=raw, reason="processing_error")
        log.exception("train worker failure job_id=%s", job_uuid)

    return True


def main() -> None:
    log.info("Calotype train worker — queue %s", QUEUE_TRAIN)
    redis = redis_from_env()
    publisher = RedisQueuePublisher(redis)
    factory = get_session_factory()

    configure_logging()
    start_heartbeat_thread("/tmp/lr_ff_train_worker.heartbeat")

    n = reap_stuck_jobs(factory, queue_name=QUEUE_TRAIN, publisher=publisher, kinds=["train"])
    if n:
        log.warning("reaper: recovered %d stuck jobs at startup", n)
    start_reaper_thread(factory, queue_name=QUEUE_TRAIN, publisher=publisher, kinds=["train"], logger=log)

    while True:
        try:
            if not process_one(redis, factory):
                time.sleep(0.05)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            # Redis restarted or the network hiccupped: keep the worker alive and retry.
            log.warning("redis unavailable, retrying in 2s: %s", exc)
            time.sleep(2)
        except KeyboardInterrupt:
            print("Stopping train worker", file=sys.stderr)
            raise SystemExit(0)


if __name__ == "__main__":
    main()
