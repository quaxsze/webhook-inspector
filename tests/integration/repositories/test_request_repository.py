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


async def test_list_filters_by_q_against_method_path_body(session):
    """Search filters rows by q across method/path/body_preview/headers."""
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    await repo.save(
        CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="POST",
            path="/stripe",
            query_string=None,
            headers={"content-type": "application/json"},
            body=b"payment_intent.succeeded",
            source_ip="127.0.0.1",
            inline_threshold_bytes=8192,
        )
    )
    await repo.save(
        CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="GET",
            path="/health",
            query_string=None,
            headers={"content-type": "application/json"},
            body=b"pong",
            source_ip="127.0.0.1",
            inline_threshold_bytes=8192,
        )
    )
    await repo.save(
        CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="POST",
            path="/github",
            query_string=None,
            headers={"content-type": "application/json"},
            body=b"push event",
            source_ip="127.0.0.1",
            inline_threshold_bytes=8192,
        )
    )
    await session.commit()

    matching = await repo.list_by_endpoint(endpoint.id, q="payment_intent.succeeded")
    assert len(matching) == 1
    assert matching[0].path == "/stripe"

    # 'pong' matches the body_preview of the /health request (the simple
    # tokenizer treats '/health' as a single atom, so we search on its body).
    health = await repo.list_by_endpoint(endpoint.id, q="pong")
    assert len(health) == 1
    assert health[0].path == "/health"


async def test_list_with_q_none_returns_all(session):
    """No q filter returns all rows (V1 behavior preserved)."""
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    for path in ("/a", "/b"):
        await repo.save(
            CapturedRequest.create(
                endpoint_id=endpoint.id,
                method="POST",
                path=path,
                query_string=None,
                headers={},
                body=b"x",
                source_ip="127.0.0.1",
                inline_threshold_bytes=8192,
            )
        )
    await session.commit()

    all_rows = await repo.list_by_endpoint(endpoint.id, q=None)
    assert len(all_rows) == 2


async def test_list_with_q_uses_and_semantics(session):
    """plainto_tsquery uses AND between words."""
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    for path, body in [("/a", b"foo bar baz"), ("/b", b"foo only")]:
        await repo.save(
            CapturedRequest.create(
                endpoint_id=endpoint.id,
                method="POST",
                path=path,
                query_string=None,
                headers={},
                body=body,
                source_ip="127.0.0.1",
                inline_threshold_bytes=8192,
            )
        )
    await session.commit()

    rows = await repo.list_by_endpoint(endpoint.id, q="foo bar")
    assert len(rows) == 1
    assert rows[0].path == "/a"


async def test_stream_for_export_yields_all_rows_up_to_max(session):
    """stream_for_export yields all rows ordered by received_at DESC, capped at max_count."""
    from datetime import UTC, datetime, timedelta

    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    now = datetime.now(UTC)
    for i in range(5):
        base = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="POST",
            path=f"/r{i}",
            query_string=None,
            headers={},
            body=f"body-{i}".encode(),
            source_ip="127.0.0.1",
            inline_threshold_bytes=8192,
        )
        # Force monotonically increasing received_at so r0 is oldest, r4 newest
        req = CapturedRequest(
            id=base.id,
            endpoint_id=base.endpoint_id,
            method=base.method,
            path=base.path,
            query_string=base.query_string,
            headers=base.headers,
            body_preview=base.body_preview,
            body_size=base.body_size,
            blob_key=base.blob_key,
            source_ip=base.source_ip,
            received_at=now - timedelta(seconds=5 - i),
        )
        await repo.save(req)
    await session.commit()

    rows = []
    async for r in repo.stream_for_export(endpoint.id, max_count=3):
        rows.append(r)
    assert len(rows) == 3
    assert [r.path for r in rows] == ["/r4", "/r3", "/r2"]


async def test_count_by_endpoint(session):
    """count_by_endpoint returns total captured request count."""
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    assert await repo.count_by_endpoint(endpoint.id) == 0

    for _ in range(3):
        await repo.save(
            CapturedRequest.create(
                endpoint_id=endpoint.id,
                method="POST",
                path="/x",
                query_string=None,
                headers={},
                body=b"x",
                source_ip="127.0.0.1",
                inline_threshold_bytes=8192,
            )
        )
    await session.commit()

    assert await repo.count_by_endpoint(endpoint.id) == 3
