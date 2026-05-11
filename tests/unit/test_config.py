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
