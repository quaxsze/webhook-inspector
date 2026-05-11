from abc import ABC, abstractmethod


class BlobStorage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...
