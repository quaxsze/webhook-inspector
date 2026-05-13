from datetime import UTC, datetime, timedelta
from uuid import uuid4

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)


async def test_save_and_find_by_token(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="abc123", ttl_days=7)

    await repo.save(endpoint)
    await session.commit()

    found = await repo.find_by_token("abc123")
    assert found is not None
    assert found.id == endpoint.id
    assert found.token == "abc123"
    assert found.request_count == 0


async def test_find_by_token_returns_none_when_missing(session):
    repo = PostgresEndpointRepository(session)
    assert await repo.find_by_token("unknown") is None


async def test_increment_request_count(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="abc", ttl_days=7)
    await repo.save(endpoint)
    await session.commit()

    await repo.increment_request_count(endpoint.id)
    await repo.increment_request_count(endpoint.id)
    await session.commit()

    found = await repo.find_by_token("abc")
    assert found.request_count == 2


async def test_save_and_find_persists_custom_response_fields(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(
        token="custom-resp",
        ttl_days=7,
        response_status_code=418,
        response_body='{"teapot":true}',
        response_headers={"X-Custom": "yes"},
        response_delay_ms=200,
    )
    await repo.save(endpoint)
    await session.commit()

    found = await repo.find_by_token("custom-resp")
    assert found is not None
    assert found.response_status_code == 418
    assert found.response_body == '{"teapot":true}'
    assert found.response_headers == {"X-Custom": "yes"}
    assert found.response_delay_ms == 200


async def test_save_endpoint_with_default_response(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="default-resp", ttl_days=7)
    await repo.save(endpoint)
    await session.commit()

    found = await repo.find_by_token("default-resp")
    assert found.response_status_code == 200
    assert found.response_body == '{"ok":true}'
    assert found.response_headers == {}
    assert found.response_delay_ms == 0


async def test_delete_expired_removes_only_expired(session):
    repo = PostgresEndpointRepository(session)
    fresh = Endpoint.create(token="fresh", ttl_days=7)
    stale = Endpoint(
        id=uuid4(),
        token="stale",
        created_at=datetime.now(UTC) - timedelta(days=10),
        expires_at=datetime.now(UTC) - timedelta(days=3),
        request_count=0,
    )
    await repo.save(fresh)
    await repo.save(stale)
    await session.commit()

    deleted = await repo.delete_expired()
    await session.commit()

    assert deleted == 1
    assert await repo.find_by_token("fresh") is not None
    assert await repo.find_by_token("stale") is None
