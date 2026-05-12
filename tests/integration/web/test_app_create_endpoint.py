import httpx
import pytest
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


@pytest.mark.parametrize("base_url, expected_hook_prefix", [
    ("https://app.example.com", "https://hook.example.com/h/"),
    ("https://webhook-inspector-app-xxx.a.run.app", "https://webhook-inspector-ingestor-xxx.a.run.app/h/"),
    ("http://localhost:8000", "http://localhost:8001/h/"),
])
async def test_hook_base_url_swaps_subdomain(
    monkeypatch, database_url, engine, base_url, expected_hook_prefix
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.post("/api/endpoints")
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"].startswith(expected_hook_prefix), \
            f"Expected URL starting with {expected_hook_prefix}, got {data['url']}"
