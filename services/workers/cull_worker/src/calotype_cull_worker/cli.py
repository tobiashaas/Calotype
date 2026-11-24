"""Cull worker — sorts photos into keep / uncertain / reject with a reason (ADR 005).

Per photo the culling features are computed once from the preview and kept in
photos.analysis["cull"]. Photos of the job that already carry a decision (stars, pick/reject
flag in lr_metadata) teach the scorer; without enough of them the starter rules decide. The
loop around the job (envelope, DLQ, status) is the worker runtime's.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from uuid import UUID

import numpy as np
from PIL import Image

from calotype_culling import FaceAnalyzer, PhotoFeatures, analyze_rgb
from calotype_culling.cull import cull, decision_from_metadata
from calotype_observability import get_logger
from calotype_queue.constants import QUEUE_CULL
from calotype_queue.payloads import CullPayloadV1
from calotype_worker_runtime import JobContext, Worker, run_worker

log = get_logger("calotype.cull_worker")
FEATURES_KEY = "cull"


def features_for(image_bytes: bytes, name: str, faces: FaceAnalyzer | None) -> PhotoFeatures:
    with Image.open(io.BytesIO(image_bytes)) as im:
        rgb = np.asarray(im.convert("RGB"))
    return analyze_rgb(rgb, name, faces)


def handler(faces: FaceAnalyzer | None) -> Callable[[JobContext[CullPayloadV1]], None]:
    """The cull job, with the face analyzer the process opened once."""

    def handle(ctx: JobContext[CullPayloadV1]) -> None:
        feats: list[PhotoFeatures] = []
        decisions: list[bool | None] = []
        lightroom: list[dict | None] = []
        kept_ids: list[UUID] = []
        for photo_id in ctx.payload.photo_ids:
            with ctx.store() as store:
                ctx.progress(store)
                photo = store.photos.get(photo_id)
                if photo is None:
                    continue
                cached = (photo.analysis or {}).get(FEATURES_KEY)
                if cached:
                    f = PhotoFeatures.from_dict(cached)
                else:
                    try:
                        f = features_for(ctx.blobs.preview(photo.s3_key), str(photo_id), faces)
                    except Exception as e:  # no usable preview: no decision for this photo
                        log.warning("no usable preview, skipping photo_id=%s: %s", photo_id, e)
                        continue
                    store.photos.merge_analysis(photo_id, {FEATURES_KEY: f.to_dict()})
                feats.append(f)
                decisions.append(decision_from_metadata(photo.lr_metadata))
                # Lightroom's assisted-culling scores, read from the catalog by the Bridge.
                lightroom.append((photo.lr_metadata or {}).get("lr_culling"))
                kept_ids.append(photo_id)

        scored = sum(1 for s in lightroom if s)
        if scored:
            log.info("Lightroom culling scores for %d of %d photos job_id=%s", scored, len(lightroom), ctx.job_id)
        results = cull(feats, decisions, lightroom if scored else None) if feats else []
        with ctx.store() as store:
            for photo_id, r in zip(kept_ids, results):
                store.cull_results.upsert(job_id=ctx.job_id, photo_id=photo_id, bucket=r.bucket,
                                          score=r.score, reason=r.reason, method=r.method)
            ctx.complete(store)
        method = results[0].method if results else "-"
        log.info("cull job completed job_id=%s photos=%d method=%s", ctx.job_id, len(results), method)

    return handle


def cull_worker(faces: FaceAnalyzer | None) -> Worker[CullPayloadV1]:
    return Worker(name="cull", queue=QUEUE_CULL, kind="cull", payload_model=CullPayloadV1,
                  handler=handler(faces), reaper_kinds=("cull",))


def main() -> None:
    with FaceAnalyzer() as faces:
        run_worker(cull_worker(faces))


if __name__ == "__main__":
    main()
