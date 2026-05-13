from dataclasses import dataclass

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.services.token_generator import generate_token


@dataclass
class CreateEndpoint:
    repo: EndpointRepository
    ttl_days: int

    async def execute(
        self,
        *,
        response_status_code: int = 200,
        response_body: str = '{"ok":true}',
        response_headers: dict[str, str] | None = None,
        response_delay_ms: int = 0,
    ) -> Endpoint:
        endpoint = Endpoint.create(
            token=generate_token(),
            ttl_days=self.ttl_days,
            response_status_code=response_status_code,
            response_body=response_body,
            response_headers=response_headers,
            response_delay_ms=response_delay_ms,
        )
        await self.repo.save(endpoint)
        return endpoint
