from dataclasses import dataclass

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.services.token_generator import generate_token


@dataclass
class CreateEndpoint:
    repo: EndpointRepository
    ttl_days: int

    async def execute(self) -> Endpoint:
        endpoint = Endpoint.create(token=generate_token(), ttl_days=self.ttl_days)
        await self.repo.save(endpoint)
        return endpoint
