import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service


async def test_list_returns_empty_for_new_endpoint(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]
        resp = await c.get(f"/api/endpoints/{token}/requests")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_before_id": None}


async def test_list_unknown_token_returns_404(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get("/api/endpoints/missing/requests")
        assert resp.status_code == 404
