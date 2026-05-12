from abc import ABC, abstractmethod
from uuid import UUID

from webhook_inspector.domain.entities.endpoint import Endpoint


class EndpointRepository(ABC):
    @abstractmethod
    async def save(self, endpoint: Endpoint) -> None: ...

    @abstractmethod
    async def find_by_token(self, token: str) -> Endpoint | None: ...

    @abstractmethod
    async def find_by_id(self, endpoint_id: UUID) -> Endpoint | None: ...

    @abstractmethod
    async def increment_request_count(self, endpoint_id: UUID) -> None: ...

    @abstractmethod
    async def delete_expired(self) -> int:
        """Delete expired endpoints. Returns count of deleted rows."""
