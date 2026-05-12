"""GCS-backed BlobStorage adapter.

Uses google-cloud-storage with asyncio.to_thread to wrap the sync client.
For Phase B, this is acceptable performance-wise (blob writes are off the
hot path of the request). Phase C may switch to gcloud-aio-storage for
native async.
"""

import asyncio

from google.cloud import storage  # type: ignore[attr-defined]
from google.cloud.exceptions import NotFound

from webhook_inspector.domain.ports.blob_storage import BlobStorage


class GcsBlobStorage(BlobStorage):
    def __init__(self, bucket_name: str, key_prefix: str = "") -> None:
        self._bucket_name = bucket_name
        self._key_prefix = key_prefix.rstrip("/")
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    async def put(self, key: str, data: bytes) -> None:
        full_key = self._full_key(key)
        await asyncio.to_thread(self._upload, full_key, data)

    async def get(self, key: str) -> bytes | None:
        full_key = self._full_key(key)
        try:
            return await asyncio.to_thread(self._download, full_key)
        except NotFound:
            return None

    def _full_key(self, key: str) -> str:
        if self._key_prefix:
            return f"{self._key_prefix}/{key}"
        return key

    def _upload(self, key: str, data: bytes) -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_string(data)

    def _download(self, key: str) -> bytes:
        blob = self._bucket.blob(key)
        return bytes(blob.download_as_bytes())
