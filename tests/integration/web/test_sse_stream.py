import asyncio

import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_sse_delivers_new_request_event(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps

    # Reset all app_deps module-level notifier singleton
    app_deps._notifier = None
    ing_deps._notifier = None

    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]

    # Accumulate SSE body parts delivered to the httpx ASGITransport send callback.
    # ASGITransport buffers chunks internally but does forward them via response body.
    # We capture all body bytes by letting the SSE run briefly then cancelling.
    body_parts: list[bytes] = []

    async def run_sse():
        """Run the SSE stream endpoint directly via ASGI, capturing body chunks.

        ASGITransport cannot interleave streaming with external sends, so we
        drive the ASGI interface manually and collect body chunks as they arrive.
        """
        # We run the app via ASGI directly to capture streaming chunks.
        scope = {
            "type": "http",
            "method": "GET",
            "path": f"/stream/{token}",
            "query_string": b"",
            "headers": [],
            "http_version": "1.1",
        }
        response_started = asyncio.Event()
        connection_done = asyncio.Event()

        async def receive():
            # Wait until we decide to close the connection
            await connection_done.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                response_started.set()
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    body_parts.append(chunk)
                if not message.get("more_body", True):
                    connection_done.set()

        await app_service(scope, receive, send)

    # Start SSE consumer as background task
    consumer = asyncio.create_task(run_sse())

    # Wait for SSE LISTEN to be established (notifier.subscribe must be running)
    await asyncio.sleep(0.5)

    # Send a webhook request
    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        await c.post(f"/h/{token}", content=b"hello")

    # Give the SSE event time to arrive and be processed
    await asyncio.sleep(0.5)

    # Stop the SSE stream by cancelling the consumer
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    full = b"".join(body_parts).decode()
    assert "data:" in full
    assert "POST" in full
