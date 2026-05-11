from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID


class Notifier(ABC):
    @abstractmethod
    async def publish_new_request(self, endpoint_id: UUID, request_id: UUID) -> None: ...

    @abstractmethod
    def subscribe(self, endpoint_id: UUID) -> AsyncIterator[UUID]:
        """Yields request_id values for each new request on the endpoint."""
