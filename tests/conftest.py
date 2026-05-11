import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> AsyncIterator[PostgresContainer]:
    container = PostgresContainer("postgres:16", driver="psycopg")
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    # psycopg3 supports async natively via postgresql+psycopg:// — no driver rename needed
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
async def engine(database_url: str):
    eng = create_async_engine(database_url, future=True)
    async with eng.begin() as conn:
        # Register all models
        from webhook_inspector.infrastructure.database import models  # noqa: F401

        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s
        await s.rollback()
