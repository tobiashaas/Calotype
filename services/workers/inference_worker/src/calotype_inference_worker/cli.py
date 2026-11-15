"""Inference worker — applies profile model to photos and saves EditResults."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from uuid import UUID, uuid4

import boto3
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.orm import sessionmaker

from calotype_edit_serializer import apply_style, edited_photos, from_lightroom, keeps_as_shot, serialize_for_lightroom
from calotype_domain.jobs import JobStatus
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION, artifact_feature_version, run_inference
from calotype_inference_pipeline.shoot import calibrate
from calotype_inference_pipeline.straighten import MIN_LINES, crop_settings
from calotype_observability import configure_logging, get_logger, set_request_id, start_heartbeat_thread
from calotype_persistence.repositories.edit_results import EditResultRepository
from calotype_persistence.repositories.feature_vectors import FeatureVectorRepository
from calotype_persistence.repositories.jobs import JobRepository
from calotype_persistence.repositories.photos import PhotoRepository
from calotype_persistence.repositories.profiles import ProfileRepository
from calotype_persistence.session import get_session_factory, session_scope
from calotype_queue import consumer
from calotype_queue.constants import QUEUE_INFERENCE
from calotype_queue.publisher import redis_from_env

log = get_logger("calotype.inference_worker")


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minio"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "miniosecret_changeme"),
        region_name="us-east-1",
    )



def straighten_settings(analysis: dict | None) -> dict:
    """Lightroom crop keys that level the photo — only with clear reference lines, else none."""
    tilt = (analysis or {}).get("straighten") or {}
    size = (analysis or {}).get("preview_size") or []
    angle = float(tilt.get("crop_angle") or 0.0)
    if not angle or int(tilt.get("lines") or 0) < MIN_LINES or len(size) != 2:
        return {}
    # Lightroom's crop corners refer to the sensor image; sensors are landscape, the preview
    # may be upright portrait — only the aspect ratio matters.
    return crop_settings(angle, max(size), min(size))


def capture_time(exif: dict | None) -> float | None:
    """Seconds of the capture time (`date_time_original`, ISO 8601) — None if unknown.

    Only differences within one shoot matter, so a time zone offset is ignored.
    """
    raw = (exif or {}).get("date_time_original")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19]).timestamp()
    except ValueError:
        return None


def calibrate_to_shoot(
    predictions: dict[UUID, dict[str, float]],
    vectors: dict[UUID, list[float]],
    settings: dict[UUID, dict],
    photo_ids: list[UUID],
    format_type: str,
    job_uuid: UUID,
    times: dict[UUID, float | None] | None = None,
    with_model: bool = True,
) -> list[UUID]:
    """Learn the shoot's look from the photos already edited in the selection.

    Rewrites ``predictions`` of the other photos in place and returns them (the photos to
    edit); the edited photos are examples only and keep the photographer's settings. Without
    edited photos (or nothing left to edit) every prediction stays as the profile made it.
    With capture times for all photos, the closest edited photo in time is one more candidate
    (series of the same scene). with_model False: there is no profile (``predictions`` hold
    empty dicts), so the edited photos are the only source of the look — none is an error.
    """
    edited = dict(zip(photo_ids, edited_photos([settings[p] for p in photo_ids], format_type)))
    refs = [p for p in predictions if edited[p]]
    rest = [p for p in predictions if not edited[p]]
    if not with_model and not refs:
        raise ValueError("no edited photos in the selection to learn the look from")
    if not refs or not rest:
        log.info("no shoot calibration (examples=%d, to edit=%d) job_id=%s", len(refs), len(rest), job_uuid)
        return list(predictions)
    times = times or {}
    timed = all(times.get(p) is not None for p in refs + rest)
    references = [from_lightroom(settings[p], format_type) for p in refs]
    if not with_model:
        # Without a profile, a RAW example still on the camera's white balance has no Kelvin
        # to pass on: the other photos then keep their own (no temp/tint in the result).
        for p, ref in zip(refs, references):
            if keeps_as_shot(settings[p], format_type):
                ref.pop("temp", None)
                ref.pop("tint", None)
    calibrated, methods = calibrate(
        references,
        [predictions[p] for p in refs] if with_model else None,
        [vectors[p] for p in refs],
        [predictions[p] for p in rest] if with_model else None,
        [vectors[p] for p in rest],
        [times[p] for p in refs] if timed else None,
        [times[p] for p in rest] if timed else None,
    )
    for p, values in zip(rest, calibrated):
        predictions[p] = values
    log.info("shoot calibration from %d edited photos, %d to edit, capture times %s, methods %s job_id=%s",
             len(refs), len(rest), timed, methods, job_uuid)
    return rest


def process_one(redis: Redis, factory: sessionmaker) -> bool:
    envelope, raw = consumer.blpop_envelope(redis, QUEUE_INFERENCE, timeout_seconds=5)
    if envelope is None and raw is None:
        return False
    if envelope is None:
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_INFERENCE, raw_payload=raw, reason="invalid_envelope")
        return True

    if envelope.job_kind != "edit":
        consumer.push_dead_letter(redis, primary_queue_name=QUEUE_INFERENCE, raw_payload=raw or "", reason=f"unexpected_job_kind:{envelope.job_kind}")
        return True

    job_uuid = UUID(envelope.job_id)
    profile_id_str = envelope.payload.get("profile_id")
    photo_ids = [UUID(pid) for pid in envelope.payload.get("photo_ids", [])]
    straighten = bool(envelope.payload.get("straighten"))
    learn_from_edits = bool(envelope.payload.get("learn_from_edits"))
    set_request_id(envelope.trace_context.get("request_id", ""))

    try:
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.RUNNING)

        profile_id: UUID | None = None
        model_bytes: bytes | None = None
        if profile_id_str:
            profile_id = UUID(profile_id_str)
            # Load profile + model artifact
            with session_scope(factory) as session:
                profile = ProfileRepository.get_by_id(session, profile_id)
                if profile is None:
                    raise ValueError(f"profile {profile_id} not found")
                artifact_key = profile.model_artifact_key
                format_type = profile.format_type
                # Style layer: the profile's preset adds the look on top of each prediction.
                base_preset = dict(profile.base_preset or {})

            # No model → fail the job. Zero predictions would reset the user's photos.
            if not artifact_key:
                raise ValueError(f"profile {profile_id} has no model artifact")
            s3 = _s3_client()
            bucket = os.environ.get("S3_BUCKET", "calotype-photos")
            model_bytes = s3.get_object(Bucket=bucket, Key=artifact_key)["Body"].read()
            # The model was trained on one feature version; use exactly that one.
            feature_version = artifact_feature_version(model_bytes)
        elif learn_from_edits and envelope.payload.get("format_type") in ("raw", "jpeg_tiff"):
            # No profile: the selection's edited photos are the only source of the look.
            format_type = envelope.payload["format_type"]
            base_preset = {}
            feature_version = CURRENT_FEATURE_VERSION
        else:
            raise ValueError("missing profile_id in payload (without one, learn_from_edits and format_type)")

        # Model prediction per photo; photos without features (no usable preview) get no result.
        predictions: dict[UUID, dict[str, float]] = {}
        vectors: dict[UUID, list[float]] = {}
        settings: dict[UUID, dict] = {}
        times: dict[UUID, float | None] = {}
        for photo_id in photo_ids:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                photo = PhotoRepository.get_by_id(session, photo_id)
                settings[photo_id] = dict(photo.lr_develop_settings or {}) if photo else {}
                times[photo_id] = capture_time(photo.exif_snapshot if photo else None)
                fv = FeatureVectorRepository.get_by_photo_id(session, photo_id, feature_version)
                if fv is None:
                    log.warning("no %s feature vector, skipping photo_id=%s job_id=%s",
                                feature_version, photo_id, job_uuid)
                    continue
                vectors[photo_id] = list(fv.vector)
                predictions[photo_id] = run_inference(model_bytes, vectors[photo_id]) if model_bytes else {}

        targets = list(predictions)
        if learn_from_edits:
            targets = calibrate_to_shoot(predictions, vectors, settings, photo_ids, format_type, job_uuid, times,
                                         with_model=model_bytes is not None)

        for photo_id in targets:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                lr_settings = apply_style(serialize_for_lightroom(predictions[photo_id], format_type), base_preset)
                if straighten:
                    photo = PhotoRepository.get_by_id(session, photo_id)
                    lr_settings.update(straighten_settings(photo.analysis if photo else None))

                EditResultRepository.upsert(
                    session,
                    result_id=uuid4(),
                    job_id=job_uuid,
                    photo_id=photo_id,
                    profile_id=profile_id,
                    lr_settings=lr_settings,
                )
            log.info("inference done photo_id=%s job_id=%s", photo_id, job_uuid)

        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.COMPLETED)

        log.info("inference job completed job_id=%s photos=%d", job_uuid, len(photo_ids))

    except Exception as exc:
        # Short, user-facing reason (shown in Lightroom); the traceback goes to the log.
        reason = f"{type(exc).__name__}: {exc}"[:500]
        with session_scope(factory) as session:
            JobRepository.set_status(session, job_uuid, JobStatus.FAILED, failure_reason=reason)
        if raw is not None:
            consumer.push_dead_letter(redis, primary_queue_name=QUEUE_INFERENCE, raw_payload=raw, reason="processing_error")
        log.exception("inference worker failure job_id=%s", job_uuid)

    return True


def main() -> None:
    log.info("Calotype inference worker — queue %s", QUEUE_INFERENCE)
    redis = redis_from_env()
    factory = get_session_factory()

    configure_logging()
    start_heartbeat_thread("/tmp/lr_ff_inference_worker.heartbeat")

    # No reaper here: a stuck edit job restarts from the feature queue (feature worker owns it).

    while True:
        try:
            if not process_one(redis, factory):
                time.sleep(0.05)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            # Redis restarted or the network hiccupped: keep the worker alive and retry.
            log.warning("redis unavailable, retrying in 2s: %s", exc)
            time.sleep(2)
        except KeyboardInterrupt:
            print("Stopping inference worker", file=sys.stderr)
            raise SystemExit(0)


if __name__ == "__main__":
    main()
