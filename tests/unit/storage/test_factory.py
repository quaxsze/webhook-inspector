import pytest

from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.storage.factory import make_blob_storage
from webhook_inspector.infrastructure.storage.s3_blob_storage import S3BlobStorage


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://x@y/z",
        **overrides,
    )


def test_factory_returns_s3_when_backend_is_s3():
    s = _settings(
        blob_storage_backend="s3",
        s3_endpoint_url="https://acc.r2.cloudflarestorage.com",
        s3_bucket_name="wi-blobs",
        s3_access_key_id="ak",
        s3_secret_access_key="sk",
    )
    storage = make_blob_storage(s)
    assert isinstance(storage, S3BlobStorage)


def test_factory_raises_when_s3_config_incomplete():
    s = _settings(blob_storage_backend="s3", s3_bucket_name="wi-blobs")
    with pytest.raises(ValueError, match="S3"):
        make_blob_storage(s)
