from __future__ import annotations

import asyncio

import boto3
from botocore.exceptions import ClientError

from app.shared.config import Settings


class StorageError(RuntimeError):
    """Raised when object storage cannot persist a file."""


class S3StorageConnector:
    connector_id = "s3"
    version = "v1"

    def __init__(self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._bucket_ready = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3StorageConnector":
        return cls(
            endpoint_url=settings.s3_endpoint,
            access_key=settings.s3_access_key or "",
            secret_key=settings.s3_secret_key or "",
            bucket=settings.s3_bucket,
        )

    async def put(self, key: str, content: bytes) -> None:
        await asyncio.to_thread(self._put_sync, key, content)

    def _put_sync(self, key: str, content: bytes) -> None:
        self._ensure_bucket()
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=content)
        except ClientError as error:
            raise StorageError("object storage write failed") from error

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)
        self._bucket_ready = True
