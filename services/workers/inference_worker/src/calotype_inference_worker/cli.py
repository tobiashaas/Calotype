"""Inference worker — applies profile model to photos and saves EditResults.

Loads the profile and the selection's photos, runs the edit plan (`plan.py`) and saves one
EditResult per planned photo. The loop around the job (envelope, DLQ, status) is the worker
runtime's. No reaper here: a stuck edit job restarts from the feature queue.
"""

from __future__ import annotations

from uuid import uuid4

from calotype_domain.failures import ProfileNotReadyError
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION, artifact_feature_version
from calotype_observability import get_logger
from calotype_queue.constants import QUEUE_INFERENCE
from calotype_queue.payloads import EditPayloadV1
from calotype_worker_runtime import JobContext, Worker, run_worker

from calotype_inference_worker.plan import EditProfile, EditRequest, ExifSnapshot, ShootPhoto, plan_edit

log = get_logger("calotype.inference_worker")


def _load_profile(ctx: JobContext[EditPayloadV1]) -> tuple[EditProfile, str]:
    """The profile to edit with and the feature version its model was trained on."""
    payload = ctx.payload
    if payload.profile_id is None:
        # No profile: the selection's edited photos are the only source of the look
        # (the payload model guarantees learn_from_edits and format_type then).
        return EditProfile(payload.format_type), CURRENT_FEATURE_VERSION
    with ctx.store() as store:
        record = store.profiles.get(payload.profile_id)
        if record is None:
            raise ProfileNotReadyError(f"profile {payload.profile_id} not found")
        artifact_key = record.model_artifact_key
        format_type = record.format_type
        base_preset = dict(record.base_preset or {})
        retouch = dict(record.retouch or {})
    # No model → fail the job. Zero predictions would reset the user's photos.
    if not artifact_key:
        raise ProfileNotReadyError(f"profile {payload.profile_id} has no model artifact")
    model_bytes = ctx.blobs.model(artifact_key)
    # The model was trained on one feature version; use exactly that one.
    feature_version = artifact_feature_version(model_bytes)
    return EditProfile.from_model(model_bytes, format_type, base_preset, retouch), feature_version


def handle(ctx: JobContext[EditPayloadV1]) -> None:
    payload = ctx.payload
    request = EditRequest.from_payload(payload.model_dump())
    profile, feature_version = _load_profile(ctx)
    if request.look is not None:
        log.info("look chosen for the job job_id=%s", ctx.job_id)

    # Load: every photo of the selection; photos without features (no usable preview)
    # take part in telling edited from untouched, but get no result.
    photos: list[ShootPhoto] = []
    for photo_id in payload.photo_ids:
        with ctx.store() as store:
            ctx.progress(store)
            photo = store.photos.get(photo_id)
            fv = store.feature_vectors.get(photo_id, feature_version)
            if fv is None:
                log.warning("no %s feature vector, skipping photo_id=%s job_id=%s",
                            feature_version, photo_id, ctx.job_id)
            photos.append(ShootPhoto(
                photo_id=photo_id,
                settings=dict(photo.lr_develop_settings or {}) if photo else {},
                vector=list(fv.vector) if fv is not None else None,
                exif=ExifSnapshot.from_snapshot(photo.exif_snapshot if photo else None),
                analysis=dict(photo.analysis or {}) if photo else None,
            ))

    plan = plan_edit(request, profile, photos)
    for note in plan.notes:
        log.info("%s job_id=%s", note, ctx.job_id)

    for result in plan.results:
        with ctx.store() as store:
            ctx.progress(store)
            store.edit_results.upsert(
                result_id=uuid4(),
                job_id=ctx.job_id,
                photo_id=result.photo_id,
                profile_id=payload.profile_id,
                lr_settings=result.lr_settings,
                retouch=result.retouch,
                kept_crop=result.kept_crop,
            )
        log.info("inference done photo_id=%s job_id=%s", result.photo_id, ctx.job_id)

    with ctx.store() as store:
        ctx.complete(store)
    log.info("inference job completed job_id=%s photos=%d", ctx.job_id, len(payload.photo_ids))


WORKER = Worker(
    name="inference",
    queue=QUEUE_INFERENCE,
    kind="edit",
    payload_model=EditPayloadV1,
    handler=handle,
    # No reaper_kinds: a stuck edit job restarts from the feature queue (feature worker owns it).
)


def main() -> None:
    run_worker(WORKER)


if __name__ == "__main__":
    main()
