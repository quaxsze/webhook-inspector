"""Regression test for the NOTIFY-before-COMMIT race condition.

The original bug: in CaptureRequest, request_repo.save() flushed but didn't
commit; then notifier.publish_new_request() emitted on an autonomous connection;
then session_scope finally committed. SSE consumers receiving the NOTIFY found
no row and dropped the event silently.

This test verifies that by the time we receive a notification, the row exists.
"""

import asyncio
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.infrastructure.notifications.postgres_notifier import (
    PostgresNotifier,
)
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)


def _sync_dsn(async_url: str) -> str:
    return async_url.replace("+psycopg_async", "").replace("+psycopg", "")


async def test_notification_arrives_only_after_row_is_visible(
    database_url, session_factory: async_sessionmaker
):
    """The NOTIFY must fire after commit, so listeners can SELECT the row."""
    notifier = PostgresNotifier(dsn=_sync_dsn(database_url))
    await notifier.start()

    # Seed an endpoint
    async with session_factory() as s:
        repo = PostgresEndpointRepository(s)
        endpoint = Endpoint.create(token=f"race-{uuid4().hex[:8]}", ttl_days=7)
        await repo.save(endpoint)
        await s.commit()

    received_ids = []
    consumer_can_see_rows = []

    async def consume_once():
        async for req_id in notifier.subscribe(endpoint.id):
            received_ids.append(req_id)
            # Critical: by the time we see the NOTIFY, the row MUST be visible
            async with session_factory() as s:
                rrepo = PostgresRequestRepository(s)
                row = await rrepo.find_by_id(req_id)
            consumer_can_see_rows.append(row is not None)
            return

    task = asyncio.create_task(consume_once())
    await asyncio.sleep(0.1)  # let LISTEN register

    # Save a request via the repository (which must emit the NOTIFY post-commit)
    async with session_factory() as s:
        rrepo = PostgresRequestRepository(s)
        request = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="POST",
            path=f"/h/{endpoint.token}",
            query_string=None,
            headers={},
            body=b"race-test",
            source_ip="192.0.2.1",
            inline_threshold_bytes=8192,
        )
        await rrepo.save(request)
        await s.commit()

    await asyncio.wait_for(task, timeout=3.0)
    await notifier.stop()

    assert received_ids == [request.id]
    assert consumer_can_see_rows == [True], (
        "Row was not visible when notification arrived — NOTIFY fired before COMMIT"
    )
