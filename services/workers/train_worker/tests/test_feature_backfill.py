"""Train worker computes missing feature vectors instead of failing (no DB/S3 needed)."""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
from PIL import Image

from lr_frameflow_train_worker import cli


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, Bucket: str, Key: str):  # noqa: N803 — boto3 signature
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 40)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def repos(monkeypatch):
    stored: dict[uuid.UUID, list[float]] = {}
    linked: dict[uuid.UUID, uuid.UUID] = {}

    def get_by_photo_id(session, photo_id, model_version=None):
        vec = stored.get(photo_id)
        return SimpleNamespace(vector=vec) if vec is not None else None

    def create(session, *, vector_id, photo_id, model_version, vector):
        stored[photo_id] = vector

    monkeypatch.setattr(cli.FeatureVectorRepository, "get_by_photo_id", staticmethod(get_by_photo_id))
    monkeypatch.setattr(cli.FeatureVectorRepository, "create", staticmethod(create))
    monkeypatch.setattr(
        cli.PhotoRepository,
        "set_feature_vector_id",
        staticmethod(lambda session, pid, fid: linked.__setitem__(pid, fid)),
    )
    return stored, linked


def test_missing_vector_is_extracted_and_stored(repos):
    stored, linked = repos
    photo = SimpleNamespace(id=uuid.uuid4(), s3_key="photos/a.jpg")
    vec = cli._ensure_feature_vector(None, FakeS3({"photos/a.jpg": _jpeg()}), "b", photo)
    assert vec is not None and len(vec) == 153 and any(vec)  # feature version 2
    assert stored[photo.id] == vec
    assert photo.id in linked


def test_existing_vector_is_reused(repos):
    stored, _ = repos
    photo = SimpleNamespace(id=uuid.uuid4(), s3_key="photos/missing.jpg")
    stored[photo.id] = [0.5] * 153
    assert cli._ensure_feature_vector(None, FakeS3({}), "b", photo) == [0.5] * 153


@pytest.mark.parametrize("objects", [{}, {"photos/a.jpg": b"not a jpeg"}])
def test_unusable_preview_returns_none_and_stores_nothing(repos, objects):
    stored, _ = repos
    photo = SimpleNamespace(id=uuid.uuid4(), s3_key="photos/a.jpg")
    assert cli._ensure_feature_vector(None, FakeS3(objects), "b", photo) is None
    assert photo.id not in stored
