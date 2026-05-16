from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tests.fakes.metrics_collector import FakeMetricsCollector
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.jobs.cleaner import run_cleanup


async def test_run_cleanup_removes_expired_endpoints(session_factory, database_url):
    async with session_factory() as s:
        repo = PostgresEndpointRepository(s)
        fresh = Endpoint.create(token="fresh-cleanup", ttl_days=7)
        stale = Endpoint(
            id=uuid4(),
            token="stale-cleanup",
            created_at=datetime.now(UTC) - timedelta(days=10),
            expires_at=datetime.now(UTC) - timedelta(days=3),
            request_count=0,
        )
        await repo.save(fresh)
        await repo.save(stale)
        await s.commit()

    deleted = await run_cleanup(database_url=database_url)
    assert deleted >= 1

    async with session_factory() as s:
        repo = PostgresEndpointRepository(s)
        assert await repo.find_by_token("fresh-cleanup") is not None
        assert await repo.find_by_token("stale-cleanup") is None


async def test_cleaner_emits_heartbeat_metric_even_when_no_deletes(session_factory, database_url):
    sync_dsn = database_url.replace("+psycopg_async", "+psycopg")
    metrics = FakeMetricsCollector()

    deleted = await run_cleanup(database_url=sync_dsn, metrics=metrics)

    assert deleted == 0
    assert metrics.cleaner_runs == [0]
