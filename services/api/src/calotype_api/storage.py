"""MinIO / S3-compatible storage client."""

from __future__ import annotations

import os
from typing import BinaryIO

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError


_DEFAULTS = {
    "endpoint": "http://127.0.0.1:9000",
    "access_key": "minio",
    "secret_key": "miniosecret_changeme",
    "bucket": "calotype-photos",
}


def get_s3_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", _DEFAULTS["endpoint"]),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", _DEFAULTS["access_key"]),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", _DEFAULTS["secret_key"]),
        region_name="us-east-1",  # required by boto3 even for MinIO
    )


def ensure_bucket(client: BaseClient, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def upload_photo(client: BaseClient, key: str, data: bytes | BinaryIO) -> str:
    bucket = os.environ.get("S3_BUCKET", _DEFAULTS["bucket"])
    ensure_bucket(client, bucket)
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/jpeg")
    return key
