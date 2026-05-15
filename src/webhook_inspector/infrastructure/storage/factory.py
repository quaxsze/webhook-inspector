from webhook_inspector.config import Settings
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


def make_blob_storage(settings: Settings) -> BlobStorage:
    backend = settings.blob_storage_backend.lower()
    if backend == "local":
        return LocalBlobStorage(base_path=settings.blob_storage_path)
    if backend == "gcs":
        if not settings.gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME must be set when BLOB_STORAGE_BACKEND=gcs")
        # Import here to avoid importing google-cloud-storage when not used
        from webhook_inspector.infrastructure.storage.gcs_blob_storage import (
            GcsBlobStorage,
        )

        return GcsBlobStorage(bucket_name=settings.gcs_bucket_name)
    if backend == "s3":
        missing = [
            n
            for n, v in (
                ("S3_ENDPOINT_URL", settings.s3_endpoint_url),
                ("S3_BUCKET_NAME", settings.s3_bucket_name),
                ("S3_ACCESS_KEY_ID", settings.s3_access_key_id),
                ("S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key),
            )
            if not v
        ]
        if missing:
            raise ValueError(f"S3 backend requires: {', '.join(missing)}")
        from webhook_inspector.infrastructure.storage.s3_blob_storage import (
            S3BlobStorage,
        )

        return S3BlobStorage(
            endpoint_url=settings.s3_endpoint_url,  # type: ignore[arg-type]
            bucket_name=settings.s3_bucket_name,  # type: ignore[arg-type]
            access_key_id=settings.s3_access_key_id,  # type: ignore[arg-type]
            secret_access_key=settings.s3_secret_access_key,  # type: ignore[arg-type]
            region=settings.s3_region,
        )
    raise ValueError(f"unknown blob storage backend: {backend!r}")
