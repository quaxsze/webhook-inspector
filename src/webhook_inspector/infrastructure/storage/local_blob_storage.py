import asyncio
from pathlib import Path

from webhook_inspector.domain.ports.blob_storage import BlobStorage


class LocalBlobStorage(BlobStorage):
    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: bytes) -> None:
        target = self._resolve_safe(key)
        await asyncio.to_thread(self._write, target, data)

    async def get(self, key: str) -> bytes | None:
        target = self._resolve_safe(key)
        if not target.exists():
            return None
        return await asyncio.to_thread(target.read_bytes)

    def _resolve_safe(self, key: str) -> Path:
        target = (self._base / key).resolve()
        if not str(target).startswith(str(self._base)):
            raise ValueError(f"invalid key: {key!r}")
        return target

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
