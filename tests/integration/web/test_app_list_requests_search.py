import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app


def _reset_deps():
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()


async def test_q_filters_results(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    _reset_deps()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]

        from webhook_inspector.web.ingestor.main import app as ingestor_app

        async with httpx.AsyncClient(
            transport=ASGITransport(app=ingestor_app), base_url="http://test"
        ) as ing:
            await ing.post(f"/h/{token}", content=b"payment_intent.succeeded")
            await ing.post(f"/h/{token}", content=b"unrelated content")

        resp = await c.get(
            f"/api/endpoints/{token}/requests",
            params={"q": "payment_intent.succeeded"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1


async def test_q_empty_returns_all(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    _reset_deps()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]

        from webhook_inspector.web.ingestor.main import app as ingestor_app

        async with httpx.AsyncClient(
            transport=ASGITransport(app=ingestor_app), base_url="http://test"
        ) as ing:
            await ing.post(f"/h/{token}", content=b"foo")
            await ing.post(f"/h/{token}", content=b"bar")

        # No q param -> both rows
        resp_no_q = await c.get(f"/api/endpoints/{token}/requests")
        assert resp_no_q.status_code == 200
        assert len(resp_no_q.json()["items"]) == 2


async def test_fragment_endpoint_returns_html_filtered_by_q(
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
            await ing.post(f"/h/{token}", content=b"payment_intent.succeeded")
            await ing.post(f"/h/{token}", content=b"unrelated content")

        resp = await c.get(
            f"/api/endpoints/{token}/requests.fragment",
            params={"q": "payment_intent.succeeded"},
        )
        assert resp.status_code == 200
        # Returns HTML <li> rows (no <ul> wrapper) for HTMX innerHTML swap.
        body = resp.text
        assert "<li" in body
        # Only the matching row should be present.
        assert body.count("<li") == 1


async def test_q_too_long_returns_400(monkeypatch, database_url, engine, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    _reset_deps()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]
        resp = await c.get(f"/api/endpoints/{token}/requests", params={"q": "x" * 201})
        assert resp.status_code == 400
