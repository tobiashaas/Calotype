"""Blob store: the key layout stays byte-identical, both adapters behave alike."""

from __future__ import annotations

import io
import uuid

import pytest
from botocore.exceptions import ClientError

from calotype_io import BlobNotFoundError, MemoryBlobStore, S3BlobStore, model_key, preview_key

PHOTO = uuid.UUID("11111111-2222-3333-4444-555555555555")
PROFILE = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def test_key_layout_is_what_existing_buckets_hold():
    assert preview_key(PHOTO) == "photos/11111111-2222-3333-4444-555555555555.jpg"
    assert model_key(PROFILE, "histstats-face-v2") == (
        "models/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/model-histstats-face-v2.joblib")
    assert model_key(f"job-{PHOTO}", "histogram-v1") == (
        "models/job-11111111-2222-3333-4444-555555555555/model-histogram-v1.joblib")


class FakeS3:
    """The few boto3 calls the adapter makes, against a dict of buckets."""

    def __init__(self, buckets: dict[str, dict[str, bytes]] | None = None) -> None:
        self.buckets = buckets if buckets is not None else {}
        self.content_types: dict[str, str] = {}

    def head_bucket(self, Bucket):  # noqa: N803 — boto3 signature
        if Bucket not in self.buckets:
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def create_bucket(self, Bucket):  # noqa: N803
        self.buckets[Bucket] = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.buckets[Bucket][Key] = Body
        self.content_types[Key] = ContentType

    def get_object(self, Bucket, Key):  # noqa: N803
        try:
            return {"Body": io.BytesIO(self.buckets[Bucket][Key])}
        except KeyError:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject") from None


def test_s3_creates_the_bucket_and_writes_under_the_layout():
    s3 = FakeS3()
    blobs = S3BlobStore(s3, "calotype-photos")
    assert blobs.put_preview(PHOTO, b"jpeg") == preview_key(PHOTO)
    assert blobs.put_model(PROFILE, "v2", b"model") == model_key(PROFILE, "v2")
    assert s3.buckets["calotype-photos"] == {preview_key(PHOTO): b"jpeg", model_key(PROFILE, "v2"): b"model"}
    assert s3.content_types == {preview_key(PHOTO): "image/jpeg", model_key(PROFILE, "v2"): "application/octet-stream"}


def test_s3_reads_existing_objects_by_their_stored_key():
    s3 = FakeS3({"b": {"photos/old.jpg": b"old preview", "models/p/model-histogram-v1.joblib": b"m1"}})
    blobs = S3BlobStore(s3, "b")
    assert blobs.preview("photos/old.jpg") == b"old preview"
    assert blobs.model("models/p/model-histogram-v1.joblib") == b"m1"
    with pytest.raises(ClientError):
        blobs.preview(PHOTO)


def test_s3_from_env_defaults_to_the_local_stack(monkeypatch):
    for name in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    blobs = S3BlobStore.from_env()
    assert blobs.bucket == "calotype-photos"
    assert blobs._client.meta.endpoint_url == "http://127.0.0.1:9000"
    monkeypatch.setenv("S3_BUCKET", "lr-frameflow-photos")
    monkeypatch.setenv("S3_ENDPOINT", "http://127.0.0.1:9200")
    blobs = S3BlobStore.from_env()
    assert (blobs.bucket, blobs._client.meta.endpoint_url) == ("lr-frameflow-photos", "http://127.0.0.1:9200")


def test_memory_store_round_trips_and_misses_loudly():
    blobs = MemoryBlobStore()
    key = blobs.put_preview(PHOTO, b"jpeg")
    assert blobs.preview(PHOTO) == blobs.preview(key) == b"jpeg"
    mkey = blobs.put_model(PROFILE, "v2", b"model")
    assert blobs.model(mkey) == b"model"
    with pytest.raises(BlobNotFoundError):
        blobs.model(model_key(PROFILE, "v1"))
