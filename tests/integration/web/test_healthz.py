import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_app_healthz_returns_ok_when_db_reachable(monkeypatch, database_url, engine):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_service), base_url="http://test"
    ) as c:
        resp = await c.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["checks"]["database"] == "ok"


async def test_ingestor_healthz_returns_ok_when_db_reachable(
    monkeypatch, database_url, engine, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.ingestor import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()
    deps._blob_storage.cache_clear()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=ingestor_service), base_url="http://test"
    ) as c:
        resp = await c.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["blob_storage"] == "ok"
