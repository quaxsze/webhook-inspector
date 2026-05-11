from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from webhook_inspector.application.use_cases.capture_request import CaptureRequest
from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)
from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = _session_factory()
    async with factory() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
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


async def get_capture_request(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    notifier: PostgresNotifier = Depends(get_notifier),
) -> CaptureRequest:
    return CaptureRequest(
        endpoint_repo=PostgresEndpointRepository(session),
        request_repo=PostgresRequestRepository(session),
        blob_storage=LocalBlobStorage(settings.blob_storage_path),
        notifier=notifier,
        inline_threshold=settings.body_inline_threshold_bytes,
    )
