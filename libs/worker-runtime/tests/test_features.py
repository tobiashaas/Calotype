"""Feature store: a stored vector is reused, a missing one computed and stored, an unusable
preview gives None and stores nothing (a zero vector would poison training)."""

from __future__ import annotations

import uuid

import pytest

from calotype_io import MemoryBlobStore
from calotype_persistence.memory import MemoryStore
from calotype_worker_runtime import FeatureStore


def compute(data: bytes, version: str) -> list[float]:
    if data == b"broken":
        raise ValueError("cannot decode")
    return [0.0, 0.0] if data == b"black" else [float(len(data)), 1.0]


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def _photo(store, blobs, preview: bytes | None):
    photo_id = uuid.uuid4()
    key = blobs.put_preview(photo_id, preview) if preview is not None else f"photos/{photo_id}.jpg"
    return store.photos.create(photo_id=photo_id, lr_catalog_uuid=str(photo_id), s3_key=key,
                               exif_snapshot={}, lr_develop_settings={})


def test_missing_vector_is_computed_stored_and_linked(store):
    blobs = MemoryBlobStore()
    photo = _photo(store, blobs, b"jpeg")
    assert FeatureStore(blobs, compute).vector(store, photo, "v2") == [4.0, 1.0]
    stored = store.feature_vectors.get(photo.id, "v2")
    assert list(stored.vector) == [4.0, 1.0]
    assert store.photos.get(photo.id).feature_vector_id == stored.id
    assert store.feature_vectors.get(photo.id, "v1") is None


def test_stored_vector_is_reused_without_the_preview(store):
    blobs = MemoryBlobStore()
    photo = _photo(store, blobs, None)
    store.feature_vectors.create(vector_id=uuid.uuid4(), photo_id=photo.id, model_version="v2", vector=[0.5] * 3)
    assert FeatureStore(blobs, compute).vector(store, photo, "v2") == [0.5] * 3


def test_bytes_in_hand_are_used_instead_of_a_download(store):
    blobs = MemoryBlobStore()
    photo = _photo(store, blobs, None)
    assert FeatureStore(blobs, compute).vector(store, photo, "v2", preview=b"ab") == [2.0, 1.0]


@pytest.mark.parametrize("preview", [None, b"broken", b"black"])
def test_unusable_preview_gives_none_and_stores_nothing(store, preview):
    blobs = MemoryBlobStore()
    photo = _photo(store, blobs, preview)
    assert FeatureStore(blobs, compute).vector(store, photo, "v2") is None
    assert store.feature_vectors.get(photo.id, "v2") is None
    assert store.photos.get(photo.id).feature_vector_id is None
