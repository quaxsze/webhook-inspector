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


@pytest.mark.parametrize(
    ("base_url", "expected_hook_prefix"),
    [
        ("https://app.example.com", "https://hook.example.com/h/"),
        (
            "https://webhook-inspector-app-xxx.a.run.app",
            "https://webhook-inspector-ingestor-xxx.a.run.app/h/",
        ),
        ("http://localhost:8000", "http://localhost:8001/h/"),
    ],
)
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
        assert data["url"].startswith(expected_hook_prefix), (
            f"Expected URL starting with {expected_hook_prefix}, got {data['url']}"
        )


async def test_post_endpoints_with_custom_response_payload(monkeypatch, database_url, engine):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    payload = {
        "response": {
            "status_code": 201,
            "body": '{"created":true}',
            "headers": {"X-Foo": "bar"},
            "delay_ms": 50,
        }
    }
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/endpoints", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["response"]["status_code"] == 201
        assert data["response"]["body"] == '{"created":true}'
        assert data["response"]["headers"] == {"X-Foo": "bar"}
        assert data["response"]["delay_ms"] == 50


@pytest.mark.parametrize(
    ("bad_response", "expected_detail_substring"),
    [
        ({"status_code": 700}, "status_code"),
        ({"delay_ms": 60000}, "delay_ms"),
        ({"body": "x" * 70000}, "body"),
        ({"headers": {"Content-Length": "0"}}, "Content-Length"),
    ],
)
async def test_post_endpoints_validation_errors(
    monkeypatch, database_url, engine, bad_response, expected_detail_substring
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps

    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/endpoints", json={"response": bad_response})
        assert resp.status_code == 400
        assert expected_detail_substring.lower() in resp.text.lower()
