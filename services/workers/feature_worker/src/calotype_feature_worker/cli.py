"""Feature-stage worker: extract features for edit-job photos, forward to inference queue.

Per photo: the feature vector of every supported version (a profile trained on v1 needs v1, a
new one v2) and the preview analysis (straighten estimate), each computed once and reused by
every later edit job. The loop around the job (envelope, DLQ, status) is the worker runtime's.
"""

from __future__ import annotations

import io

from PIL import Image

from calotype_inference_pipeline import SUPPORTED_FEATURE_VERSIONS, compute_features
from calotype_inference_pipeline.straighten import estimate_tilt
from calotype_observability import get_logger
from calotype_queue.constants import QUEUE_FEATURE
from calotype_queue.payloads import EditPayloadV1
from calotype_worker_runtime import JobContext, Worker, run_worker

log = get_logger("calotype.feature_worker")


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


def handle(ctx: JobContext[EditPayloadV1]) -> None:
    photo_ids = ctx.payload.photo_ids
    for photo_id in photo_ids:
        with ctx.store() as store:
            ctx.progress(store)
            photo = store.photos.get(photo_id)
            if photo is None:
                log.warning("photo not found, skipping photo_id=%s job_id=%s", photo_id, ctx.job_id)
                continue

            missing = [v for v in SUPPORTED_FEATURE_VERSIONS
                       if store.feature_vectors.get(photo_id, v) is None]
            needs_analysis = "straighten" not in (photo.analysis or {})
            if not missing and not needs_analysis:
                log.info("feature vectors already exist, reusing photo_id=%s", photo_id)
                continue

            # One download for the analysis and every missing version.
            try:
                image_bytes = ctx.blobs.preview(photo.s3_key)
            except Exception as e:
                log.warning("could not download preview, skipping photo_id=%s: %s", photo_id, e)
                continue

            if needs_analysis:
                analysis = analyze_preview(image_bytes)
                if analysis:
                    store.photos.merge_analysis(photo_id, analysis)
            for version in missing:
                ctx.features.vector(store, photo, version, preview=image_bytes)

        log.info("features extracted photo_id=%s job_id=%s", photo_id, ctx.job_id)

    ctx.forward_to_inference()
    log.info("forwarded to inference job_id=%s photos=%d", ctx.job_id, len(photo_ids))


WORKER = Worker(
    name="feature",
    queue=QUEUE_FEATURE,
    kind="edit",
    payload_model=EditPayloadV1,
    handler=handle,
    reaper_kinds=("edit",),  # an edit job starts here; a stuck one restarts here
    compute_features=compute_features,
)


def main() -> None:
    run_worker(WORKER)


if __name__ == "__main__":
    main()
