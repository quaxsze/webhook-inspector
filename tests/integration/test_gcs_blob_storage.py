"""Integration tests for GcsBlobStorage.

These tests use the `google-cloud-storage` library with a fake in-memory
implementation (`gcsfs` or `fakeredis`-style helpers don't exist for GCS).
Instead, we use a real GCS bucket via Application Default Credentials, or
skip if running without GCP auth.

To run locally, set GCS_TEST_BUCKET to a bucket you can read+write.
In CI, skip (no GCP credentials).
"""

import os
import uuid

import pytest

from webhook_inspector.infrastructure.storage.gcs_blob_storage import GcsBlobStorage

pytestmark = pytest.mark.skipif(
    not os.getenv("GCS_TEST_BUCKET"),
    reason="GCS_TEST_BUCKET not set — skipping live GCS integration tests",
)


@pytest.fixture
def bucket_name() -> str:
    return os.environ["GCS_TEST_BUCKET"]


@pytest.fixture
def test_prefix() -> str:
    # Unique prefix per test run to avoid collisions
    return f"test-{uuid.uuid4()}"


@pytest.fixture
async def storage(bucket_name: str, test_prefix: str) -> GcsBlobStorage:
    return GcsBlobStorage(bucket_name=bucket_name, key_prefix=test_prefix)


async def test_put_then_get_roundtrip(storage: GcsBlobStorage):
    await storage.put("foo/bar", b"hello gcs")
    assert await storage.get("foo/bar") == b"hello gcs"


async def test_get_missing_returns_none(storage: GcsBlobStorage):
    assert await storage.get("does/not/exist") is None


async def test_put_overwrites_existing(storage: GcsBlobStorage):
    await storage.put("key", b"v1")
    await storage.put("key", b"v2")
    assert await storage.get("key") == b"v2"
