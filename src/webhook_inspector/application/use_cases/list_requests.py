from dataclasses import dataclass
from uuid import UUID

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.exceptions import EndpointNotFoundError
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.request_repository import RequestRepository

# Re-export for backward compat with callers that import from this module.
__all__ = ["EndpointNotFoundError", "ListRequests"]


@dataclass
class ListRequests:
    endpoint_repo: EndpointRepository
    request_repo: RequestRepository

    async def execute(
        self,
        token: str,
        limit: int = 50,
        before_id: UUID | None = None,
        q: str | None = None,
    ) -> list[CapturedRequest]:
        endpoint = await self.endpoint_repo.find_by_token(token)
        if endpoint is None:
            raise EndpointNotFoundError(token)
        return await self.request_repo.list_by_endpoint(
            endpoint_id=endpoint.id,
            limit=limit,
            before_id=before_id,
            q=q,
        )
