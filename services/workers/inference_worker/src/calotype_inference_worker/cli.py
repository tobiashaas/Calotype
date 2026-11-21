"""Inference worker — applies profile model to photos and saves EditResults."""

from __future__ import annotations

import math
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

from calotype_edit_serializer import (
    apply_preset,
    apply_style,
    edited_photos,
    from_lightroom,
    keeps_as_shot,
    serialize_for_lightroom,
    shared_masks,
    shared_style,
)
from calotype_domain.jobs import JobStatus
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION, artifact_feature_version, run_inference
from calotype_inference_pipeline.series import smooth
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


def measured_light(exif: dict | None) -> float | None:
    """What the camera measured as colour temperature (Kelvin, read from the RAW by the
    Bridge) — None if unknown."""
    value = (exif or {}).get("wb_measured_kelvin")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def camera_exposure(exif: dict | None) -> list[float] | None:
    """The camera's exposure settings as features: log2 of ISO, shutter time (seconds) and
    f-number, plus the exposure compensation (0 when not recorded) — None unless ISO, time and
    aperture are known."""
    exif = exif or {}

    def number(key: str) -> float | None:
        value = exif.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    iso, shutter, aperture = number("iso"), number("shutter_speed"), number("aperture")
    if not iso or not shutter or not aperture or min(iso, shutter, aperture) <= 0:
        return None
    return [math.log2(iso), math.log2(shutter), math.log2(aperture), number("exposure_bias") or 0.0]


def calibrate_to_shoot(
    predictions: dict[UUID, dict[str, float]],
    vectors: dict[UUID, list[float]],
    settings: dict[UUID, dict],
    photo_ids: list[UUID],
    format_type: str,
    job_uuid: UUID,
    times: dict[UUID, float | None] | None = None,
    with_model: bool = True,
    light: dict[UUID, float | None] | None = None,
    camera: dict[UUID, list[float] | None] | None = None,
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
    light = light or {}
    lit = all(light.get(p) is not None for p in refs + rest)
    camera = camera or {}
    exposed = all(camera.get(p) is not None for p in refs + rest)
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
        [light[p] for p in refs] if lit else None,
        [light[p] for p in rest] if lit else None,
        [camera[p] for p in refs] if exposed else None,
        [camera[p] for p in rest] if exposed else None,
    )
    for p, values in zip(rest, calibrated):
        predictions[p] = values
    log.info("shoot calibration from %d edited photos, %d to edit, capture times %s, camera light %s, "
             "camera exposure %s, methods %s job_id=%s", len(refs), len(rest), timed, lit, exposed, methods, job_uuid)
    return rest


def smooth_series(
    predictions: dict[UUID, dict[str, float]],
    vectors: dict[UUID, list[float]],
    settings: dict[UUID, dict],
    targets: list[UUID],
    format_type: str,
    job_uuid: UUID,
    times: dict[UUID, float | None],
) -> bool:
    """Pull exposure and white balance of each series together (rewrites ``predictions`` of
    the targets in place). Photos of the selection that are no target are the photographer's
    edited examples: they keep their values and anchor their series. Needs the capture time
    of every photo; returns whether anything was smoothed."""
    nodes = list(predictions)
    if len(nodes) < 2 or any(times.get(p) is None for p in nodes):
        log.info("no series consistency (photos=%d, capture times missing) job_id=%s", len(nodes), job_uuid)
        return False
    wanted = set(targets)
    values = []
    for p in nodes:
        if p in wanted:
            values.append(predictions[p])
            continue
        example = from_lightroom(settings[p], format_type)
        if keeps_as_shot(settings[p], format_type):
            # Still on the camera's white balance: nothing the photographer chose to pass on.
            example.pop("temp", None)
            example.pop("tint", None)
        values.append(example)
    smoothed = smooth(values, [vectors[p] for p in nodes], [times[p] for p in nodes],
                      [p not in wanted for p in nodes])
    for p, row in zip(nodes, smoothed):
        if p in wanted:
            predictions[p] = row
    log.info("series consistency over %d photos (%d fixed examples) job_id=%s",
             len(nodes), len(nodes) - len(wanted), job_uuid)
    return True


def examples_look(predictions: dict[UUID, dict], targets: list[UUID], settings: dict[UUID, dict]) -> dict:
    """The look settings (tone curve, HSL, color grading, glow …) the edited photos of the
    shoot share — the examples are the photos with features that are no target."""
    wanted = set(targets)
    return shared_style([settings[p] for p in predictions if p not in wanted])


def job_preset(payload: dict, profile_preset: dict) -> dict:
    """The preset whose look goes on top of the predictions: one chosen for this job (one of
    the photographer's own presets) replaces the profile's."""
    chosen = payload.get("base_preset")
    return dict(chosen) if isinstance(chosen, dict) and chosen else profile_preset


def styled(predicted: dict, preset: dict, chosen: bool) -> dict:
    """A profile's preset adds only its look; a preset chosen for the job is used as by hand —
    its tone sliders too, exposure and white balance per photo (``apply_preset``)."""
    return apply_preset(predicted, preset) if chosen else apply_style(predicted, preset)


def examples_masks(predictions: dict[UUID, dict], targets: list[UUID], settings: dict[UUID, dict]) -> dict:
    """The mask strengths (subject, sky …) the edited photos of the shoot share."""
    wanted = set(targets)
    return shared_masks([settings[p] for p in predictions if p not in wanted])


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
    consistent_series = bool(envelope.payload.get("consistent_series"))
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
                retouch = dict(profile.retouch or {})

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
            retouch = {}
            feature_version = CURRENT_FEATURE_VERSION
        else:
            raise ValueError("missing profile_id in payload (without one, learn_from_edits and format_type)")
        if envelope.payload.get("base_preset"):
            log.info("look chosen for the job job_id=%s", job_uuid)
        base_preset = job_preset(envelope.payload, base_preset)
        chosen_look = bool(envelope.payload.get("base_preset"))

        # Model prediction per photo; photos without features (no usable preview) get no result.
        predictions: dict[UUID, dict[str, float]] = {}
        vectors: dict[UUID, list[float]] = {}
        settings: dict[UUID, dict] = {}
        times: dict[UUID, float | None] = {}
        light: dict[UUID, float | None] = {}
        camera: dict[UUID, list[float] | None] = {}
        for photo_id in photo_ids:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                photo = PhotoRepository.get_by_id(session, photo_id)
                settings[photo_id] = dict(photo.lr_develop_settings or {}) if photo else {}
                times[photo_id] = capture_time(photo.exif_snapshot if photo else None)
                light[photo_id] = measured_light(photo.exif_snapshot if photo else None)
                camera[photo_id] = camera_exposure(photo.exif_snapshot if photo else None)
                fv = FeatureVectorRepository.get_by_photo_id(session, photo_id, feature_version)
                if fv is None:
                    log.warning("no %s feature vector, skipping photo_id=%s job_id=%s",
                                feature_version, photo_id, job_uuid)
                    continue
                vectors[photo_id] = list(fv.vector)
                predictions[photo_id] = run_inference(model_bytes, vectors[photo_id]) if model_bytes else {}

        targets = list(predictions)
        look: dict = {}
        if learn_from_edits:
            targets = calibrate_to_shoot(predictions, vectors, settings, photo_ids, format_type, job_uuid, times,
                                         with_model=model_bytes is not None, light=light,
                                         camera=camera)
            # The shoot's own look wins over the profile's preset: it is what this shoot got.
            look = examples_look(predictions, targets, settings)
            log.info("shoot look from the edited photos: %d settings (%s) job_id=%s",
                     len(look), ", ".join(sorted(k for k in look if look[k]))[:300], job_uuid)
            # Same for the masks: with examples, their mask setup replaces the profile's (a
            # shoot without sky masks in its examples gets none from the profile either).
            if targets != list(predictions):
                retouch = examples_masks(predictions, targets, settings)
                log.info("mask strengths from the edited photos: %s job_id=%s", retouch, job_uuid)

        if consistent_series:
            smooth_series(predictions, vectors, settings, targets, format_type, job_uuid, times)

        for photo_id in targets:
            with session_scope(factory) as session:
                JobRepository.touch(session, job_uuid)
                lr_settings = styled(serialize_for_lightroom(predictions[photo_id], format_type), base_preset, chosen_look)
                lr_settings.update(look)
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
                    retouch=retouch or None,
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
