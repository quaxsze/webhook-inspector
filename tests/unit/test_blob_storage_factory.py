import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


def _import_factory():
    # Lazy import so we can re-import after env changes
    from webhook_inspector.infrastructure.storage import factory

    return factory


def test_factory_returns_local_when_backend_is_local(tmp_path):
    env = {
        "BLOB_STORAGE_BACKEND": "local",
        "BLOB_STORAGE_PATH": str(tmp_path),
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings

        settings = Settings()
        storage = _import_factory().make_blob_storage(settings)
        assert isinstance(storage, LocalBlobStorage)


def test_factory_raises_when_gcs_backend_without_bucket():
    env = {
        "BLOB_STORAGE_BACKEND": "gcs",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings

        settings = Settings()
        with pytest.raises(ValueError, match="GCS_BUCKET_NAME"):
            _import_factory().make_blob_storage(settings)


def test_factory_raises_on_unknown_backend():
    """Pydantic itself rejects backend values not in the Literal."""
    env = {
        "BLOB_STORAGE_BACKEND": "redis",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings

        with pytest.raises(ValidationError):
            Settings()


def test_factory_returns_gcs_when_backend_is_gcs_with_bucket():
    """The happy path for GCS backend instantiates GcsBlobStorage with the bucket."""
    env = {
        "BLOB_STORAGE_BACKEND": "gcs",
        "GCS_BUCKET_NAME": "test-bucket-name",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings
        from webhook_inspector.infrastructure.storage.gcs_blob_storage import GcsBlobStorage

        with patch("google.cloud.storage.Client") as mock_client:
            mock_client.return_value = MagicMock()
            settings = Settings()
            storage = _import_factory().make_blob_storage(settings)
            assert isinstance(storage, GcsBlobStorage)
