from collections.abc import AsyncIterator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_inspector.application.use_cases.list_requests import EndpointNotFoundError
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=select_autoescape())


async def stream_for_token(
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    notifier: PostgresNotifier,
) -> AsyncIterator[str]:
    async with session_factory() as session:
        endpoint = await PostgresEndpointRepository(session).find_by_token(token)
    if endpoint is None:
        raise EndpointNotFoundError(token)

    yield ": connected\n\n"

    fragment = _env.get_template("request_fragment.html")
    async for request_id in notifier.subscribe(endpoint.id):
        async with session_factory() as session:
            req = await PostgresRequestRepository(session).find_by_id(request_id)
        if req is None:
            continue
        html = fragment.render(
            req={
                "method": req.method,
                "path": req.path,
                "body_size": req.body_size,
                "received_at": req.received_at.isoformat(),
            }
        )
        # SSE multi-line data: one "data:" per line
        encoded = "\n".join(f"data: {line}" for line in html.splitlines())
        yield f"event: message\n{encoded}\n\n"
