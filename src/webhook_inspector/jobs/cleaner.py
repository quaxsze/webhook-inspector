import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


async def run_cleanup(database_url: str) -> int:
    engine = create_async_engine(database_url, future=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            deleted = await PostgresEndpointRepository(session).delete_expired()
            await session.commit()
            logger.info("cleanup_complete", extra={"deleted": deleted})
            return deleted
    finally:
        await engine.dispose()


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-cleaner")
    configure_tracing(settings.service_name + "-cleaner", settings.environment, None)
    deleted = asyncio.run(run_cleanup(settings.database_url))
    sys.stdout.write(f"deleted {deleted} expired endpoints\n")


if __name__ == "__main__":
    main()
