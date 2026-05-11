import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app


async def test_post_endpoints_returns_url_and_expiry(monkeypatch, database_url, engine):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    # Reset deps cache
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/endpoints")
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"].startswith("http")
        assert "/h/" in data["url"]
        assert "expires_at" in data
