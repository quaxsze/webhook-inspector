import json

import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app


def _reset_deps():
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()


async def test_export_returns_streaming_json_with_attachment_header(
    monkeypatch, database_url, engine, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    _reset_deps()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]

        from webhook_inspector.web.ingestor.main import app as ingestor_app

        async with httpx.AsyncClient(
            transport=ASGITransport(app=ingestor_app), base_url="http://test"
        ) as ing:
            await ing.post(f"/h/{token}", content=b'{"a":1}')
            await ing.post(f"/h/{token}", content=b'{"b":2}')

        resp = await c.get(f"/api/endpoints/{token}/export.json")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert "attachment" in resp.headers["content-disposition"].lower()
        assert token in resp.headers["content-disposition"]

        data = json.loads(resp.text)
        assert data["endpoint"]["token"] == token
        assert data["exported_request_count"] == 2
        assert len(data["requests"]) == 2
        bodies = {r["body"] for r in data["requests"]}
        assert bodies == {'{"a":1}', '{"b":2}'}


async def test_export_404_when_endpoint_missing(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    _reset_deps()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/endpoints/nonexistent/export.json")
        assert resp.status_code == 404


async def test_export_413_when_over_cap(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EXPORT_MAX_REQUESTS", "1")
    _reset_deps()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]

        from webhook_inspector.web.ingestor.main import app as ingestor_app

        async with httpx.AsyncClient(
            transport=ASGITransport(app=ingestor_app), base_url="http://test"
        ) as ing:
            await ing.post(f"/h/{token}", content=b"a")
            await ing.post(f"/h/{token}", content=b"b")

        resp = await c.get(f"/api/endpoints/{token}/export.json")
        assert resp.status_code == 413
