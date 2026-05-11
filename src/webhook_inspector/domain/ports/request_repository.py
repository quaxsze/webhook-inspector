from abc import ABC, abstractmethod
from uuid import UUID

from webhook_inspector.domain.entities.captured_request import CapturedRequest


class RequestRepository(ABC):
    @abstractmethod
    async def save(self, request: CapturedRequest) -> None: ...

    @abstractmethod
    async def find_by_id(self, request_id: UUID) -> CapturedRequest | None: ...

    @abstractmethod
    async def list_by_endpoint(
        self,
        endpoint_id: UUID,
        limit: int = 50,
        before_id: UUID | None = None,
    ) -> list[CapturedRequest]: ...
