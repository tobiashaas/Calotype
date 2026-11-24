"""Object storage for the API: the blob store from `calotype_io` (ADR 007).

The key layout (`photos/{photo_id}.jpg`) and bucket creation live in `calotype_io.blobs`;
the API only stores previews.
"""

from __future__ import annotations

from calotype_io import BlobStore, S3BlobStore


def blob_store() -> BlobStore:
    """The S3 blob store configured from S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY.
    A new client per call — boto3 clients are not shared across request threads."""
    return S3BlobStore.from_env()
