import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service


async def test_viewer_renders_with_token(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]
        resp = await c.get(f"/{token}")
        assert resp.status_code == 200
        body = resp.text
        assert token in body
        assert "htmx" in body.lower()
        assert "sse-connect" in body


async def test_viewer_404_for_unknown_token(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get("/totally-unknown-token-here")
        assert resp.status_code == 404
