"""Feature store: a photo's feature vector of one version — stored, or computed and stored.

Used by the feature worker (every supported version, before inference) and the train worker
(the current version, for photos uploaded just before training). Without a usable preview no
vector is stored and the caller gets None: a zero vector would be reused forever and poison
training.

The function that turns preview bytes into a vector is passed in (in production
`calotype_inference_pipeline.compute_features`), so this module stays within its imports.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from calotype_io import BlobStore
from calotype_persistence.models import Photo
from calotype_persistence.stores import Store

# (preview bytes, feature version) -> vector; raises ValueError for an unusable preview.
ComputeFeatures = Callable[[bytes, str], list[float]]


class FeatureStore:
    def __init__(self, blobs: BlobStore, compute: ComputeFeatures | None,
                 log: logging.Logger | None = None) -> None:
        self._blobs = blobs
        self._compute = compute
        self._log = log or logging.getLogger("calotype.features")

    def vector(self, store: Store, photo: Photo, version: str, *,
               preview: bytes | None = None) -> list[float] | None:
        """The photo's vector of ``version``: the stored one, else computed from its preview
        (``preview`` when the caller already holds the bytes) and stored in ``store``.
        None when the preview is missing or not decodable."""
        existing = store.feature_vectors.get(photo.id, version)
        if existing is not None:
            return list(existing.vector)
        if self._compute is None:
            raise RuntimeError("this worker computes no feature vectors (Worker.compute_features)")
        if preview is None:
            try:
                preview = self._blobs.preview(photo.s3_key)
            except Exception as exc:
                self._log.warning("could not download preview, skipping photo_id=%s: %s", photo.id, exc)
                return None
        try:
            vector = self._compute(preview, version)
        except ValueError as exc:
            self._log.warning("preview not usable for %s, skipping photo_id=%s: %s", version, photo.id, exc)
            return None
        if not any(vector):
            self._log.warning("preview not decodable, skipping photo_id=%s", photo.id)
            return None
        vector_id = uuid.uuid4()
        store.feature_vectors.create(vector_id=vector_id, photo_id=photo.id, model_version=version,
                                     vector=vector)
        store.photos.set_feature_vector_id(photo.id, vector_id)
        return list(vector)
