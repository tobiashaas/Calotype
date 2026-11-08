"""Cull worker — sorts photos into keep / uncertain / reject with a reason (ADR 005).

Per photo the culling features are computed once from the preview and kept in
photos.analysis["cull"]. Photos of the job that already carry a decision (stars, pick/reject
flag in lr_metadata) teach the scorer; without enough of them the starter rules decide.
"""

from __future__ import annotations

import io
import os
import sys
import time
from uuid import UUID

import boto3
import numpy as np
from PIL import Image
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.orm import sessionmaker

from lr_frameflow_culling import FaceAnalyzer, PhotoFeatures, analyze_rgb
from lr_frameflow_culling.cull import cull, decision_from_metadata
from lr_frameflow_domain.jobs import JobStatus
from lr_frameflow_observability import configure_logging, get_logger, set_request_id, start_heartbeat_thread
from lr_frameflow_persistence.reaper import reap_stuck_jobs, start_reaper_thread
from lr_frameflow_persistence.repositories.cull_results import CullResultRepository
from lr_frameflow_persistence.repositories.jobs import JobRepository
from lr_frameflow_persistence.repositories.photos import PhotoRepository
from lr_frameflow_persistence.session import get_session_factory, session_scope
from lr_frameflow_queue import consumer
from lr_frameflow_queue.constants import QUEUE_CULL
from lr_frameflow_queue.publisher import RedisQueuePublisher, redis_from_env

log = get_logger("lr_frameflow.cull_worker")
FEATURES_KEY = "cull"


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minio"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "miniosecret_changeme"),
        region_name="us-east-1",
    )


def features_for(image_bytes: bytes, name: str, faces: FaceAnalyzer) -> PhotoFeatures:
    with Image.open(io.BytesIO(image_bytes)) as im:
        rgb = np.asarray(im.convert("RGB"))
    return analyze_rgb(rgb, name, faces)


def process_one(redis: Redis, factory: sessionmaker, faces: FaceAnalyzer) -> bool:
    envelope, raw = consumer.blpop_envelope(redis, QUEUE_CULL, timeout_seconds=5)
    if envelope is None and raw is None:
        return False
    if envelope is None:
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_CULL, raw_payload=raw, reason="invalid_envelope")
        return True
    if envelope.job_kind != "cull":
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_CULL, raw_payload=raw or "",
                                  reason=f"unexpected_job_kind:{envelope.job_kind}")
        return True

    job_uuid = UUID(envelope.job_id)
    photo_ids = [UUID(pid) for pid in envelope.payload.get("photo_ids", [])]
    set_request_id(envelope.trace_context.get("request_id", ""))
    try:
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.RUNNING)
        s3 = _s3_client()
        bucket = os.environ.get("S3_BUCKET", "lrff-photos")

        feats: list[PhotoFeatures] = []
        decisions: list[bool | None] = []
        kept_ids: list[UUID] = []
        for photo_id in photo_ids:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                photo = PhotoRepository.get_by_id(session, photo_id)
                if photo is None:
                    continue
                cached = (photo.analysis or {}).get(FEATURES_KEY)
                if cached:
                    f = PhotoFeatures.from_dict(cached)
                else:
                    try:
                        data = s3.get_object(Bucket=bucket, Key=photo.s3_key)["Body"].read()
                        f = features_for(data, str(photo_id), faces)
                    except Exception as e:  # no usable preview: no decision for this photo
                        log.warning("no usable preview, skipping photo_id=%s: %s", photo_id, e)
                        continue
                    PhotoRepository.merge_analysis(session, photo_id, {FEATURES_KEY: f.to_dict()})
                feats.append(f)
                decisions.append(decision_from_metadata(photo.lr_metadata))
                kept_ids.append(photo_id)

        results = cull(feats, decisions) if feats else []
        with session_scope(factory) as session:
            for photo_id, r in zip(kept_ids, results):
                CullResultRepository.upsert(session, job_id=job_uuid, photo_id=photo_id, bucket=r.bucket,
                                            score=r.score, reason=r.reason, method=r.method)
            JobRepository.set_status(session, job_uuid, JobStatus.COMPLETED)
        method = results[0].method if results else "-"
        log.info("cull job completed job_id=%s photos=%d method=%s", job_uuid, len(results), method)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:500]
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.FAILED, failure_reason=reason)
        if raw is not None:
            consumer.push_dead_letter(redis, primary_queue_name=QUEUE_CULL, raw_payload=raw, reason="processing_error")
        log.exception("cull worker failure job_id=%s", job_uuid)
    return True


def main() -> None:
    configure_logging()
    log.info("LR-FrameFlow cull worker — queue %s", QUEUE_CULL)
    redis = redis_from_env()
    publisher = RedisQueuePublisher(redis)
    factory = get_session_factory()
    start_heartbeat_thread("/tmp/lr_ff_cull_worker.heartbeat")
    n = reap_stuck_jobs(factory, queue_name=QUEUE_CULL, publisher=publisher, kinds=["cull"])
    if n:
        log.warning("reaper: recovered %d stuck jobs at startup", n)
    start_reaper_thread(factory, queue_name=QUEUE_CULL, publisher=publisher, kinds=["cull"], logger=log)
    with FaceAnalyzer() as faces:
        while True:
            try:
                process_one(redis, factory, faces)
            except (RedisConnectionError, RedisTimeoutError) as e:
                log.warning("redis unavailable, retrying in 2 s: %s", e)
                time.sleep(2)
            except KeyboardInterrupt:
                sys.exit(0)


if __name__ == "__main__":
    main()
