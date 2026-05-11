import asyncio
from uuid import uuid4

from webhook_inspector.infrastructure.notifications.postgres_notifier import (
    PostgresNotifier,
)


async def test_publish_then_subscribe_receives_message(database_url):
    notifier = PostgresNotifier(dsn=_to_sync_dsn(database_url))
    await notifier.start()

    endpoint_id = uuid4()
    received: list = []

    async def consume():
        async for req_id in notifier.subscribe(endpoint_id):
            received.append(req_id)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)  # ensure LISTEN active

    expected_request = uuid4()
    await notifier.publish_new_request(endpoint_id, expected_request)

    await asyncio.wait_for(task, timeout=2.0)
    await notifier.stop()

    assert received == [expected_request]


def _to_sync_dsn(async_url: str) -> str:
    return async_url.replace("+psycopg_async", "").replace("+psycopg", "")
