"""Training worker — trains a profile model from photo feature vectors.

Training rows: the features of each photo's preview (computed here when missing — freshly
uploaded photos have none yet) and the photographer's Lightroom settings as targets.

No self-learning: a photo whose current settings still hold Calotype's latest result for it —
of any job and any profile, because whichever profile set them, they are not the
photographer's — is left out unless the photographer marked it as accepted (``accepted``).
A photo changed since is a Correction and is learned; a photo Calotype never edited is a
normal training photo. Earlier training photos merged into a retrain pass the same check. The loop
around the job (envelope, DLQ, job status) is the worker runtime's; the profile's status is
this worker's: TRAINING while it runs, READY with the new model, FAILED on error — except a
retrained profile, which keeps its earlier model and stays READY.
"""

from __future__ import annotations

from calotype_domain.failures import TooFewPhotosError
from calotype_domain.profiles import ProfileStatus
from calotype_edit_serializer import shared_masks, training_target, unchanged_since
from calotype_inference_pipeline import (
    CURRENT_FEATURE_VERSION,
    MIN_SAMPLES,
    compute_features,
    train_for_version,
)
from calotype_inference_pipeline.exif import ExifSnapshot
from calotype_observability import get_logger
from calotype_persistence.stores import Store
from calotype_queue.constants import QUEUE_TRAIN
from calotype_queue.payloads import TrainPayloadV1
from calotype_worker_runtime import JobContext, Worker, run_worker

log = get_logger("calotype.train_worker")


def handle(ctx: JobContext[TrainPayloadV1]) -> None:
    payload = ctx.payload
    profile_id = payload.profile_id
    # Values only a preset left (Lightroom key -> value): not the photographer's decision.
    untouched = payload.untouched or {}
    accepted = set(payload.accepted)

    format_type = "raw"
    if profile_id is not None:
        with ctx.store() as store:
            if not payload.retrain:  # a retrained profile stays usable meanwhile
                store.profiles.set_status(profile_id, ProfileStatus.TRAINING)
            profile = store.profiles.get(profile_id)
            if profile is not None:
                format_type = profile.format_type

    feature_vectors: list[list[float]] = []
    targets: list[dict[str, float]] = []
    as_shot: list[bool] = []
    capture_times: list[float | None] = []
    used_settings: list[dict] = []
    skipped: list[str] = []
    for photo_id in payload.photo_ids:
        with ctx.store() as store:
            ctx.progress(store)
            photo = store.photos.get(photo_id)
            if photo is None:
                skipped.append(f"{photo_id}: not found")
                continue
            if photo_id not in accepted:
                results = store.edit_results.for_photo(photo_id)  # newest first
                applied = results[0] if results else None
                if applied is not None and unchanged_since(
                    applied.lr_settings or {}, photo.lr_develop_settings or {}, format_type,
                    earlier=[r.lr_settings or {} for r in results[1:]],
                ):
                    skipped.append(f"{photo_id}: still Calotype's result of job {applied.job_id}, not accepted")
                    continue
            target = training_target(photo.lr_develop_settings or {}, format_type, untouched)
            if not target.sliders:
                skipped.append(f"{photo_id}: no slider the photographer decided")
                continue
            vector = ctx.features.vector(store, photo, CURRENT_FEATURE_VERSION)
            if vector is None:
                skipped.append(f"{photo_id}: preview unavailable")
                continue
            feature_vectors.append(vector)
            targets.append(target.sliders)
            as_shot.append(target.as_shot)
            capture_times.append(ExifSnapshot.from_snapshot(photo.exif_snapshot).capture_time)
            used_settings.append(dict(photo.lr_develop_settings or {}))

    if skipped:
        log.warning("skipped %d training photos: %s", len(skipped), "; ".join(skipped[:20]))
    if len(feature_vectors) < MIN_SAMPLES:
        raise TooFewPhotosError(
            f"only {len(feature_vectors)} usable training photos, need at least {MIN_SAMPLES}"
        )

    # Photos on the camera's white balance teach their Kelvin too; at apply time a photo gets its
    # own Kelvin only in a Scene the profile saw corrected (capture times, model.py).
    undecided = {k: sum(1 for t in targets if k not in t) for k in ("highlights", "exposure", "temp")}
    log.info("white balance: %d of %d training photos as shot; undecided values %s untouched=%s",
             sum(as_shot), len(as_shot), undecided, untouched)
    model_bytes = train_for_version(feature_vectors, targets, CURRENT_FEATURE_VERSION, as_shot=as_shot,
                                    capture_times=capture_times)
    owner = profile_id if profile_id is not None else f"job-{ctx.job_id}"
    artifact_key = ctx.blobs.put_model(owner, CURRENT_FEATURE_VERSION, model_bytes)
    log.info("model artifact saved key=%s n_samples=%d", artifact_key, len(feature_vectors))

    with ctx.store() as store:
        if profile_id is not None:
            # Mask strengths the training photos share (subject shadows, sky …).
            retouch = shared_masks(used_settings)
            log.info("learned mask strengths %s profile_id=%s", retouch, profile_id)
            store.profiles.set_artifact(profile_id, model_artifact_key=artifact_key, retouch=retouch)
            store.profiles.set_status(profile_id, ProfileStatus.READY)
        ctx.complete(store)
    log.info("train job completed job_id=%s profile_id=%s", ctx.job_id, profile_id)


def on_failure(ctx: JobContext[TrainPayloadV1], store: Store, reason: str) -> None:
    """A failed training fails its profile — a retrained one keeps its model and stays READY."""
    if ctx.payload.profile_id is not None:
        status = ProfileStatus.READY if ctx.payload.retrain else ProfileStatus.FAILED
        store.profiles.set_status(ctx.payload.profile_id, status, failure_reason=reason)


WORKER = Worker(
    name="train",
    queue=QUEUE_TRAIN,
    kind="train",
    payload_model=TrainPayloadV1,
    handler=handle,
    reaper_kinds=("train",),
    on_failure=on_failure,
    compute_features=compute_features,
)


def main() -> None:
    run_worker(WORKER)


if __name__ == "__main__":
    main()
