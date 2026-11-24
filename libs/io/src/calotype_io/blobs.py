"""Blob store: where previews and models live, as one small interface (ADR 007).

The object key layout is defined here and nowhere else:

- preview of a photo: ``photos/{photo_id}.jpg`` (stored on the photo as ``photos.s3_key``)
- model of a profile: ``models/{profile_id}/model-{feature_version}.joblib`` (stored on the
  profile as ``profiles.model_artifact_key``); a model trained without a profile uses the
  owner ``job-{job_id}``

Writes return the key; the caller stores it on the record. Reads take the key the record
holds, so objects written before this module existed (or under an older layout) are still
found byte for byte.

Two adapters:

- `S3BlobStore` — any S3-compatible store (RustFS, MinIO, AWS), configured from the
  environment like every service always was.
- `MemoryBlobStore` — a dict, for tests of the API and the workers.
"""

from __future__ import annotations

import os
from typing import Protocol
from uuid import UUID

PREVIEW_CONTENT_TYPE = "image/jpeg"
MODEL_CONTENT_TYPE = "application/octet-stream"

DEFAULT_ENDPOINT = "http://127.0.0.1:9000"  # 127.0.0.1, never localhost (IPv6 hang on Windows)
DEFAULT_BUCKET = "calotype-photos"
DEFAULT_ACCESS_KEY = "minio"
DEFAULT_SECRET_KEY = "miniosecret_changeme"


def preview_key(photo_id: UUID | str) -> str:
    """The object key of a photo's preview."""
    return f"photos/{photo_id}.jpg"


def model_key(owner: UUID | str, feature_version: str) -> str:
    """The object key of a model: ``owner`` is the profile id (or ``job-<id>``)."""
    return f"models/{owner}/model-{feature_version}.joblib"


class BlobStore(Protocol):
    def preview(self, photo: UUID | str) -> bytes:
        """The preview's bytes, by photo id or by the key stored on the photo. Raises when
        the object is missing."""
        ...

    def put_preview(self, photo_id: UUID | str, data: bytes) -> str:
        """Store a photo's preview; returns its key."""
        ...

    def model(self, key: str) -> bytes:
        """A model's bytes by the key stored on the profile. Raises when it is missing."""
        ...

    def put_model(self, owner: UUID | str, feature_version: str, data: bytes) -> str:
        """Store a model; returns its key."""
        ...


def _preview_key_of(photo: UUID | str) -> str:
    return preview_key(photo) if isinstance(photo, UUID) else photo


class S3BlobStore:
    """An S3-compatible bucket. The bucket is created on the first write when missing."""

    def __init__(self, client, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    @classmethod
    def from_env(cls) -> S3BlobStore:
        """Configured by S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY."""
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", DEFAULT_ENDPOINT),
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY", DEFAULT_ACCESS_KEY),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY", DEFAULT_SECRET_KEY),
            region_name="us-east-1",  # required by boto3, ignored by RustFS / MinIO
        )
        return cls(client, os.environ.get("S3_BUCKET", DEFAULT_BUCKET))

    def _get(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def _put(self, key: str, data: bytes, content_type: str) -> str:
        self._ensure_bucket()
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def preview(self, photo: UUID | str) -> bytes:
        return self._get(_preview_key_of(photo))

    def put_preview(self, photo_id: UUID | str, data: bytes) -> str:
        return self._put(preview_key(photo_id), data, PREVIEW_CONTENT_TYPE)

    def model(self, key: str) -> bytes:
        return self._get(key)

    def put_model(self, owner: UUID | str, feature_version: str, data: bytes) -> str:
        return self._put(model_key(owner, feature_version), data, MODEL_CONTENT_TYPE)


class BlobNotFoundError(KeyError):
    """`MemoryBlobStore`: no object under that key."""


class MemoryBlobStore:
    """Blobs in a dict (key → bytes), the same key layout as `S3BlobStore`."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})

    def _get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise BlobNotFoundError(key) from None

    def preview(self, photo: UUID | str) -> bytes:
        return self._get(_preview_key_of(photo))

    def put_preview(self, photo_id: UUID | str, data: bytes) -> str:
        key = preview_key(photo_id)
        self.objects[key] = bytes(data)
        return key

    def model(self, key: str) -> bytes:
        return self._get(key)

    def put_model(self, owner: UUID | str, feature_version: str, data: bytes) -> str:
        key = model_key(owner, feature_version)
        self.objects[key] = bytes(data)
        return key
