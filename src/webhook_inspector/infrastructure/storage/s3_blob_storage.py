"""S3-compatible BlobStorage adapter (works with AWS S3, Cloudflare R2, MinIO, Tigris).

Uses boto3 with asyncio.to_thread to wrap the sync client — same pattern as
GcsBlobStorage. Blob writes are off the hot request path so the thread-pool
hop is acceptable.
"""

import asyncio

import boto3
from botocore.exceptions import ClientError

from webhook_inspector.domain.ports.blob_storage import BlobStorage


class S3BlobStorage(BlobStorage):
    def __init__(
        self,
        endpoint_url: str,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        key_prefix: str = "",
    ) -> None:
        self._bucket_name = bucket_name
        self._key_prefix = key_prefix.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    async def put(self, key: str, data: bytes) -> None:
        full_key = self._full_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket_name,
            Key=full_key,
            Body=data,
        )

    async def get(self, key: str) -> bytes | None:
        full_key = self._full_key(key)
        try:
            obj = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket_name,
                Key=full_key,
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        return bytes(obj["Body"].read())

    def _full_key(self, key: str) -> str:
        if self._key_prefix:
            return f"{self._key_prefix}/{key}"
        return key
