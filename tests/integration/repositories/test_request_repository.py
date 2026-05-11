import secrets
from uuid import uuid4

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)


async def _seed_endpoint(session) -> Endpoint:
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token=secrets.token_hex(8), ttl_days=7)
    await repo.save(endpoint)
    await session.commit()
    return endpoint


async def test_save_and_find_by_id(session):
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    req = CapturedRequest.create(
        endpoint_id=endpoint.id,
        method="POST",
        path="/h/abc",
        query_string=None,
        headers={"x-key": "v"},
        body=b'{"a":1}',
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )
    await repo.save(req)
    await session.commit()

    found = await repo.find_by_id(req.id)
    assert found is not None
    assert found.endpoint_id == endpoint.id
    assert found.method == "POST"
    assert found.headers == {"x-key": "v"}
    assert found.body_preview == '{"a":1}'


async def test_list_by_endpoint_returns_newest_first(session):
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    ids = []
    for i in range(3):
        req = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="GET",
            path=f"/h/abc/{i}",
            query_string=None,
            headers={},
            body=b"",
            source_ip="192.0.2.1",
            inline_threshold_bytes=8192,
        )
        await repo.save(req)
        ids.append(req.id)
    await session.commit()

    result = await repo.list_by_endpoint(endpoint.id, limit=10)
    assert len(result) == 3
    assert [r.id for r in result] == list(reversed(ids))


async def test_list_by_endpoint_respects_limit(session):
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)
    for i in range(5):
        await repo.save(
            CapturedRequest.create(
                endpoint_id=endpoint.id,
                method="GET",
                path=f"/h/abc/{i}",
                query_string=None,
                headers={},
                body=b"",
                source_ip="192.0.2.1",
                inline_threshold_bytes=8192,
            )
        )
    await session.commit()

    result = await repo.list_by_endpoint(endpoint.id, limit=2)
    assert len(result) == 2


async def test_find_by_id_returns_none_when_missing(session):
    repo = PostgresRequestRepository(session)
    assert await repo.find_by_id(uuid4()) is None
