import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
from psycopg import AsyncConnection

from webhook_inspector.domain.ports.notifier import Notifier

logger = logging.getLogger(__name__)


class PostgresNotifier(Notifier):
    """LISTEN/NOTIFY based notifier.

    Channel: ``new_request``
    Payload: ``"<endpoint_id>:<request_id>"``
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._listen_conn: AsyncConnection | None = None
        self._queues: dict[UUID, set[asyncio.Queue[UUID]]] = defaultdict(set)
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._listen_conn is not None:
                return
            self._listen_conn = await psycopg.AsyncConnection.connect(
                self._dsn, autocommit=True
            )
            async with self._listen_conn.cursor() as cur:
                await cur.execute("LISTEN new_request;")
            self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        async with self._lock:
            if self._reader_task is not None:
                self._reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task
                self._reader_task = None
            if self._listen_conn is not None:
                await self._listen_conn.close()
                self._listen_conn = None

    async def publish_new_request(self, endpoint_id: UUID, request_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn, autocommit=True) as conn:
            payload = f"{endpoint_id}:{request_id}"
            async with conn.cursor() as cur:
                await cur.execute("SELECT pg_notify('new_request', %s);", (payload,))

    def subscribe(self, endpoint_id: UUID) -> AsyncIterator[UUID]:
        return self._subscribe_gen(endpoint_id)

    async def _subscribe_gen(self, endpoint_id: UUID) -> AsyncIterator[UUID]:
        if self._listen_conn is None:
            await self.start()

        queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._queues[endpoint_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[endpoint_id].discard(queue)
            if not self._queues[endpoint_id]:
                del self._queues[endpoint_id]

    async def _read_loop(self) -> None:
        assert self._listen_conn is not None
        try:
            async for notif in self._listen_conn.notifies():
                try:
                    endpoint_str, request_str = notif.payload.split(":", 1)
                    endpoint_id = UUID(endpoint_str)
                    request_id = UUID(request_str)
                except ValueError:
                    logger.warning("malformed_notify_payload", extra={"payload": notif.payload})
                    continue
                for queue in list(self._queues.get(endpoint_id, ())):
                    queue.put_nowait(request_id)
        except Exception:
            logger.exception("notify_reader_crashed")
            raise
