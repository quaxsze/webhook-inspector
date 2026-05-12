from webhook_inspector.config import Settings
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


def make_blob_storage(settings: Settings) -> BlobStorage:
    backend = settings.blob_storage_backend.lower()
    if backend == "local":
        return LocalBlobStorage(base_path=settings.blob_storage_path)
    if backend == "gcs":
        if not settings.gcs_bucket_name:
            raise ValueError(
                "GCS_BUCKET_NAME must be set when BLOB_STORAGE_BACKEND=gcs"
            )
        # Import here to avoid importing google-cloud-storage when not used
        from webhook_inspector.infrastructure.storage.gcs_blob_storage import (
            GcsBlobStorage,
        )
        return GcsBlobStorage(bucket_name=settings.gcs_bucket_name)
    raise ValueError(f"unknown blob storage backend: {backend!r}")
