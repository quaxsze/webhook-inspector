import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker

from webhook_inspector.application.use_cases.list_requests import EndpointNotFoundError
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401


async def stream_for_token(
    token: str,
    session_factory: async_sessionmaker,
    notifier: PostgresNotifier,
) -> AsyncIterator[str]:
    # Resolve endpoint
    async with session_factory() as session:
        endpoint = await PostgresEndpointRepository(session).find_by_token(token)
    if endpoint is None:
        raise EndpointNotFoundError(token)

    # Heartbeat + initial connect comment
    yield ": connected\n\n"

    async for request_id in notifier.subscribe(endpoint.id):
        async with session_factory() as session:
            req = await PostgresRequestRepository(session).find_by_id(request_id)
        if req is None:
            continue
        payload = {
            "id": str(req.id),
            "method": req.method,
            "path": req.path,
            "received_at": req.received_at.isoformat(),
            "body_size": req.body_size,
        }
        yield f"event: message\ndata: {json.dumps(payload)}\n\n"
