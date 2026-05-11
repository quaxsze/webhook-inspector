from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from webhook_inspector.application.use_cases.create_endpoint import CreateEndpoint
from webhook_inspector.application.use_cases.list_requests import (
    EndpointNotFoundError,
    ListRequests,
)
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.web.app.deps import (
    _session_factory,
    get_create_endpoint,
    get_list_requests,
    get_notifier,
)
from webhook_inspector.web.app.sse import stream_for_token

router = APIRouter()


def hook_base_url(request: Request) -> str:
    """Derive the ingestor base URL from the app base URL.

    Prod: app.<domain>  →  hook.<domain>
    Local docker-compose: localhost:8000 → localhost:8001
    """
    base = str(request.base_url).rstrip("/")
    if "://app." in base:
        return base.replace("://app.", "://hook.")
    if ":8000" in base:
        return base.replace(":8000", ":8001")
    return base  # fallback (single-host dev)


class CreateEndpointResponse(BaseModel):
    url: str
    expires_at: str
    token: str


@router.post("/api/endpoints", status_code=201, response_model=CreateEndpointResponse)
async def create_endpoint(
    request: Request,
    use_case: CreateEndpoint = Depends(get_create_endpoint),  # noqa: B008
) -> CreateEndpointResponse:
    endpoint = await use_case.execute()
    return CreateEndpointResponse(
        url=f"{hook_base_url(request)}/h/{endpoint.token}",
        expires_at=endpoint.expires_at.isoformat(),
        token=endpoint.token,
    )


class RequestItem(BaseModel):
    id: UUID
    method: str
    path: str
    body_size: int
    received_at: str


class RequestList(BaseModel):
    items: list[RequestItem]
    next_before_id: UUID | None


@router.get("/api/endpoints/{token}/requests", response_model=RequestList)
async def list_requests(
    token: str,
    limit: int = 50,
    before_id: UUID | None = None,
    use_case: ListRequests = Depends(get_list_requests),  # noqa: B008
) -> RequestList:
    try:
        items = await use_case.execute(token=token, limit=limit, before_id=before_id)
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    return RequestList(
        items=[
            RequestItem(
                id=r.id,
                method=r.method,
                path=r.path,
                body_size=r.body_size,
                received_at=r.received_at.isoformat(),
            )
            for r in items
        ],
        next_before_id=items[-1].id if len(items) == limit else None,
    )


@router.get("/stream/{token}")
async def sse_stream(
    token: str,
    notifier: PostgresNotifier = Depends(get_notifier),  # noqa: B008
) -> StreamingResponse:
    try:
        gen = stream_for_token(token, _session_factory(), notifier)
        # Probe to surface 404 before opening stream
        first = await gen.__anext__()
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    async def merged() -> AsyncIterator[str]:
        yield first
        async for chunk in gen:
            yield chunk

    return StreamingResponse(
        merged(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{token}", response_class=HTMLResponse)
async def viewer(
    token: str,
    request: Request,
    use_case: ListRequests = Depends(get_list_requests),  # noqa: B008
) -> HTMLResponse:
    try:
        initial = await use_case.execute(token=token, limit=50)
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    templates = request.app.state.templates
    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            request=request,
            name="viewer.html",
            context={
                "token": token,
                "hook_url": f"{hook_base_url(request)}/h/{token}",
                "initial_requests": [
                    {
                        "method": r.method,
                        "path": r.path,
                        "body_size": r.body_size,
                        "received_at": r.received_at.isoformat(),
                    }
                    for r in initial
                ],
            },
        ),
    )
