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


async def test_pagination_handles_identical_timestamps(session):
    """When multiple requests share the exact same received_at, pagination
    must use a (timestamp, id) keyset, not just timestamp."""
    from datetime import UTC, datetime

    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    # 5 requests with identical received_at
    fixed_ts = datetime.now(UTC)
    ids = []
    for i in range(5):
        req = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="POST",
            path=f"/h/abc/{i}",
            query_string=None,
            headers={},
            body=b"",
            source_ip="192.0.2.1",
            inline_threshold_bytes=8192,
        )
        # Force identical timestamp
        req_with_fixed_ts = CapturedRequest(
            id=req.id,
            endpoint_id=req.endpoint_id,
            method=req.method,
            path=req.path,
            query_string=req.query_string,
            headers=req.headers,
            body_preview=req.body_preview,
            body_size=req.body_size,
            blob_key=req.blob_key,
            source_ip=req.source_ip,
            received_at=fixed_ts,
        )
        await repo.save(req_with_fixed_ts)
        ids.append(req_with_fixed_ts.id)
    await session.commit()

    # Page 1 : limit=2 → 2 newest (last 2 inserted, by id DESC)
    page1 = await repo.list_by_endpoint(endpoint.id, limit=2)
    assert len(page1) == 2

    # Page 2 : starts after page1's last item
    page2 = await repo.list_by_endpoint(endpoint.id, limit=2, before_id=page1[-1].id)
    assert len(page2) == 2

    # Page 3
    page3 = await repo.list_by_endpoint(endpoint.id, limit=2, before_id=page2[-1].id)
    assert len(page3) == 1

    # Union of all 3 pages = all 5 IDs, no duplicates, no gaps
    seen_ids = {r.id for r in page1 + page2 + page3}
    assert seen_ids == set(ids), f"Expected all 5 IDs across pagination, got {seen_ids}"
