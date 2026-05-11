from fastapi import APIRouter, Depends, HTTPException, Request

from webhook_inspector.application.use_cases.capture_request import (
    CaptureRequest,
    EndpointNotFoundError,
)
from webhook_inspector.config import Settings
from webhook_inspector.web.ingestor.deps import get_capture_request, get_settings

router = APIRouter()


@router.api_route(
    "/h/{token}{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def capture(
    token: str,
    rest: str,
    request: Request,
    use_case: CaptureRequest = Depends(get_capture_request),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_body_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    try:
        await use_case.execute(
            token=token,
            method=request.method,
            path=f"/h/{token}{rest}",
            query_string=request.url.query or None,
            headers={k.lower(): v for k, v in request.headers.items()},
            body=body,
            source_ip=request.client.host if request.client else "0.0.0.0",
        )
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    return {"ok": True}
