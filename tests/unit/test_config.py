import os
from unittest.mock import patch

from webhook_inspector.config import Settings


def test_settings_read_from_env():
    env = {
        "DATABASE_URL": "postgresql+psycopg://u:p@h:5432/db",
        "BLOB_STORAGE_PATH": "/tmp/blobs",
        "ENDPOINT_TTL_DAYS": "7",
        "MAX_BODY_BYTES": "1048576",
        "BODY_INLINE_THRESHOLD_BYTES": "4096",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
        assert s.blob_storage_path == "/tmp/blobs"
        assert s.endpoint_ttl_days == 7
        assert s.max_body_bytes == 1048576
        assert s.body_inline_threshold_bytes == 4096


def test_settings_have_sensible_defaults_for_local():
    env = {"DATABASE_URL": "postgresql+psycopg://u:p@h:5432/db"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.endpoint_ttl_days == 7
        assert s.max_body_bytes == 10 * 1024 * 1024
        assert s.body_inline_threshold_bytes == 8 * 1024
        assert s.environment == "local"


def test_settings_defaults_keep_gcs_and_no_otlp():
    s = Settings(database_url="postgresql+psycopg://x@y/z")
    assert s.blob_storage_backend == "local"
    assert s.otlp_endpoint is None
    assert s.s3_bucket_name is None


def test_settings_accepts_s3_backend_and_otlp(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    monkeypatch.setenv("BLOB_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "wi-blobs")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://acc.r2.cloudflarestorage.com")
    monkeypatch.setenv("OTLP_ENDPOINT", "https://api.honeycomb.io")
    s = Settings()
    assert s.blob_storage_backend == "s3"
    assert s.s3_bucket_name == "wi-blobs"
    assert s.s3_endpoint_url == "https://acc.r2.cloudflarestorage.com"
    assert s.otlp_endpoint == "https://api.honeycomb.io"
