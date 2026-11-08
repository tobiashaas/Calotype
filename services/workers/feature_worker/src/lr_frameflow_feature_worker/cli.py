"""Feature-stage worker: extract features for edit-job photos, forward to inference queue."""

from __future__ import annotations

import io
import os
import sys
import time
from uuid import UUID, uuid4

import boto3
from PIL import Image
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.orm import sessionmaker

from lr_frameflow_domain.jobs import JobStatus
from lr_frameflow_inference_pipeline import SUPPORTED_FEATURE_VERSIONS, compute_features
from lr_frameflow_inference_pipeline.straighten import estimate_tilt
from lr_frameflow_observability import configure_logging, get_logger, set_request_id, start_heartbeat_thread
from lr_frameflow_persistence.reaper import reap_stuck_jobs, start_reaper_thread
from lr_frameflow_persistence.repositories.feature_vectors import FeatureVectorRepository
from lr_frameflow_persistence.repositories.jobs import JobRepository
from lr_frameflow_persistence.repositories.photos import PhotoRepository
from lr_frameflow_persistence.session import get_session_factory, session_scope
from lr_frameflow_queue import consumer
from lr_frameflow_queue.constants import QUEUE_FEATURE
from lr_frameflow_queue.publisher import RedisQueuePublisher, redis_from_env

log = get_logger("lr_ff.feature_worker")


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minio"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "miniosecret_changeme"),
        region_name="us-east-1",
    )


def analyze_preview(image_bytes: bytes) -> dict:
    """Image analysis kept with the photo; computed once, used by every later edit job."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        tilt = estimate_tilt(img)
    except Exception as e:  # analysis is optional — never block feature extraction
        log.warning("preview analysis failed: %s", e)
        return {}
    return {
        "preview_size": list(img.size),
        "straighten": {"crop_angle": tilt.crop_angle, "lines": tilt.lines, "spread": tilt.spread},
    }


def process_one(redis: Redis, publisher: RedisQueuePublisher, factory: sessionmaker) -> bool:
    envelope, raw = consumer.blpop_envelope(redis, QUEUE_FEATURE, timeout_seconds=5)
    if envelope is None and raw is None:
        return False
    if envelope is None:
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_FEATURE, raw_payload=raw, reason="invalid_envelope")
        log.warning("dead-letter: invalid envelope")
        return True

    if envelope.job_kind != "edit":
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_FEATURE, raw_payload=raw or "", reason=f"unexpected_job_kind:{envelope.job_kind}")
        log.warning("wrong kind on feature queue job_kind=%s", envelope.job_kind)
        return True

    job_uuid = UUID(envelope.job_id)
    photo_ids = [UUID(pid) for pid in envelope.payload.get("photo_ids", [])]
    set_request_id(envelope.trace_context.get("request_id", ""))

    try:
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.RUNNING)

        s3 = _s3_client()
        bucket = os.environ.get("S3_BUCKET", "lrff-photos")

        for photo_id in photo_ids:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                photo = PhotoRepository.get_by_id(session, photo_id)
                if photo is None:
                    log.warning("photo not found, skipping photo_id=%s job_id=%s", photo_id, job_uuid)
                    continue

                # Every supported version: a profile trained on v1 needs v1, a new one v2.
                missing = [
                    v for v in SUPPORTED_FEATURE_VERSIONS
                    if FeatureVectorRepository.get_by_photo_id(session, photo_id, v) is None
                ]
                needs_analysis = "straighten" not in (photo.analysis or {})
                if not missing and not needs_analysis:
                    log.info("feature vectors already exist, reusing photo_id=%s", photo_id)
                    continue

                # Download preview from MinIO. Without a usable preview no vector is stored:
                # a zero vector would be reused forever and poison training.
                try:
                    obj = s3.get_object(Bucket=bucket, Key=photo.s3_key)
                    image_bytes = obj["Body"].read()
                except Exception as e:
                    log.warning("could not download preview, skipping photo_id=%s: %s", photo_id, e)
                    continue

                if needs_analysis:
                    analysis = analyze_preview(image_bytes)
                    if analysis:
                        PhotoRepository.merge_analysis(session, photo_id, analysis)

                for version in missing:
                    try:
                        vector = compute_features(image_bytes, version)
                    except ValueError as e:
                        log.warning("preview not usable for %s, skipping photo_id=%s: %s", version, photo_id, e)
                        continue
                    if not any(vector):
                        log.warning("preview not decodable, skipping photo_id=%s", photo_id)
                        continue
                    fv_id = uuid4()
                    FeatureVectorRepository.create(
                        session,
                        vector_id=fv_id,
                        photo_id=photo_id,
                        model_version=version,
                        vector=vector,
                    )
                    PhotoRepository.set_feature_vector_id(session, photo_id, fv_id)

            log.info("features extracted photo_id=%s job_id=%s", photo_id, job_uuid)

        publisher.forward_to_inference(envelope)
        log.info("forwarded to inference job_id=%s photos=%d", job_uuid, len(photo_ids))

    except Exception as exc:
        # Short, user-facing reason (shown in Lightroom); the traceback goes to the log.
        reason = f"{type(exc).__name__}: {exc}"[:500]
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.FAILED, failure_reason=reason)
        if raw is not None:
            consumer.push_dead_letter(redis, primary_queue_name=QUEUE_FEATURE, raw_payload=raw, reason="processing_error")
        log.exception("feature worker failure job_id=%s", job_uuid)

    return True


def main() -> None:
    log.info("LR-FrameFlow feature worker — queue %s", QUEUE_FEATURE)
    redis = redis_from_env()
    publisher = RedisQueuePublisher(redis)
    factory = get_session_factory()

    configure_logging()
    start_heartbeat_thread("/tmp/lr_ff_feature_worker.heartbeat")

    # Recover any jobs stuck in RUNNING at startup, then run periodically.
    n = reap_stuck_jobs(factory, queue_name=QUEUE_FEATURE, publisher=publisher, kinds=["edit"])
    if n:
        log.warning("reaper: recovered %d stuck jobs at startup", n)
    start_reaper_thread(factory, queue_name=QUEUE_FEATURE, publisher=publisher, kinds=["edit"], logger=log)

    while True:
        try:
            if not process_one(redis, publisher, factory):
                time.sleep(0.05)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            # Redis restarted or the network hiccupped: keep the worker alive and retry.
            log.warning("redis unavailable, retrying in 2s: %s", exc)
            time.sleep(2)
        except KeyboardInterrupt:
            print("Stopping feature worker", file=sys.stderr)
            raise SystemExit(0)


if __name__ == "__main__":
    main()
