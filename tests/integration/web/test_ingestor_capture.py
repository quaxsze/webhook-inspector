import httpx
import pytest
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


@pytest.mark.skip(reason="GET /api/endpoints/{token}/requests added in Task 17")
async def test_capture_returns_200_and_persists(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    # reset caches
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    app_deps.get_settings.cache_clear()
    app_deps._engine.cache_clear()
    app_deps._session_factory.cache_clear()
    ing_deps.get_settings.cache_clear()
    ing_deps._engine.cache_clear()
    ing_deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.post("/api/endpoints")
        token = resp.json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post(f"/h/{token}", json={"hello": "world"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get(f"/api/endpoints/{token}/requests")
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["method"] == "POST"


async def test_capture_unknown_token_404(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.ingestor import deps as ing_deps
    ing_deps.get_settings.cache_clear()
    ing_deps._engine.cache_clear()
    ing_deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post("/h/totallymade-up", json={})
        assert resp.status_code == 404


async def test_capture_rejects_oversized_body(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("MAX_BODY_BYTES", "1024")
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.post("/api/endpoints")
        token = resp.json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post(f"/h/{token}", content=b"x" * 2048)
        assert resp.status_code == 413
