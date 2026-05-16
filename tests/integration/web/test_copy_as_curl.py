import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_list_requests_exposes_headers_and_body_preview(
    monkeypatch, database_url, engine, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps

    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_service), base_url="http://test"
    ) as c:
        token = (await c.post("/api/endpoints")).json()["token"]

    async with httpx.AsyncClient(
        transport=ASGITransport(app=ingestor_service), base_url="http://hook"
    ) as c:
        await c.post(
            f"/h/{token}",
            headers={"X-Test": "value", "Content-Type": "application/json"},
            content=b'{"hello":"world"}',
        )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_service), base_url="http://test"
    ) as c:
        resp = await c.get(f"/api/endpoints/{token}/requests")
        items = resp.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert "headers" in item
        assert item["headers"].get("x-test") == "value"
        assert "body_preview" in item
        assert item["body_preview"] == '{"hello":"world"}'
