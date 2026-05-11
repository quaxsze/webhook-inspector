from pathlib import Path

import pytest

from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalBlobStorage:
    return LocalBlobStorage(base_path=str(tmp_path))


async def test_put_then_get_roundtrip(storage):
    await storage.put("abc/def", b"hello world")
    assert await storage.get("abc/def") == b"hello world"


async def test_get_missing_returns_none(storage):
    assert await storage.get("nope/nope") is None


async def test_put_creates_intermediate_dirs(storage, tmp_path):
    await storage.put("a/b/c/d.bin", b"data")
    assert (tmp_path / "a" / "b" / "c" / "d.bin").exists()


async def test_put_rejects_path_traversal(storage):
    with pytest.raises(ValueError, match="invalid key"):
        await storage.put("../escape", b"x")
