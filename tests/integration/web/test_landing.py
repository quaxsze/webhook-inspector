import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service


async def test_landing_page_renders_at_root(monkeypatch, database_url, engine):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_service), base_url="http://test"
    ) as c:
        resp = await c.get("/")
        assert resp.status_code == 200
        body = resp.text
        assert "hooktrace" in body
        assert "Create a webhook URL" in body
        assert "/api/endpoints" in body  # the htmx hx-post target
        assert resp.headers["content-type"].startswith("text/html")


async def test_landing_page_has_og_tags(monkeypatch, database_url, engine):
    """OG tags enable proper social-sharing previews."""
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_service), base_url="http://test"
    ) as c:
        resp = await c.get("/")
        assert 'property="og:title"' in resp.text
        assert 'property="og:description"' in resp.text
