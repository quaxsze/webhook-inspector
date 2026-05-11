from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from webhook_inspector.application.use_cases.create_endpoint import CreateEndpoint
from webhook_inspector.application.use_cases.list_requests import ListRequests
from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = _session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


_notifier: PostgresNotifier | None = None


async def get_notifier() -> PostgresNotifier:
    global _notifier
    if _notifier is None:
        settings = get_settings()
        sync_dsn = settings.database_url.replace("+psycopg_async", "").replace("+psycopg", "")
        _notifier = PostgresNotifier(dsn=sync_dsn)
        await _notifier.start()
    return _notifier


async def get_create_endpoint(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CreateEndpoint:
    return CreateEndpoint(
        repo=PostgresEndpointRepository(session),
        ttl_days=settings.endpoint_ttl_days,
    )


async def get_list_requests(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ListRequests:
    return ListRequests(
        endpoint_repo=PostgresEndpointRepository(session),
        request_repo=PostgresRequestRepository(session),
    )
