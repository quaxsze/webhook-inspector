import pytest
from testcontainers.minio import MinioContainer

from webhook_inspector.infrastructure.storage.s3_blob_storage import S3BlobStorage


@pytest.fixture(scope="module")
def minio():
    with MinioContainer() as m:
        client = m.get_client()
        client.make_bucket("test-bucket")
        yield m


@pytest.mark.asyncio
async def test_put_then_get_roundtrips(minio):
    cfg = minio.get_config()
    storage = S3BlobStorage(
        endpoint_url=f"http://{cfg['endpoint']}",
        bucket_name="test-bucket",
        access_key_id=cfg["access_key"],
        secret_access_key=cfg["secret_key"],
        region="us-east-1",
    )
    await storage.put("foo/bar.bin", b"hello world")
    got = await storage.get("foo/bar.bin")
    assert got == b"hello world"


@pytest.mark.asyncio
async def test_get_missing_key_returns_none(minio):
    cfg = minio.get_config()
    storage = S3BlobStorage(
        endpoint_url=f"http://{cfg['endpoint']}",
        bucket_name="test-bucket",
        access_key_id=cfg["access_key"],
        secret_access_key=cfg["secret_key"],
        region="us-east-1",
    )
    got = await storage.get("does/not/exist")
    assert got is None
