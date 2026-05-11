from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.infrastructure.database.models import EndpointTable


class PostgresEndpointRepository(EndpointRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, endpoint: Endpoint) -> None:
        row = EndpointTable(
            id=endpoint.id,
            token=endpoint.token,
            created_at=endpoint.created_at,
            expires_at=endpoint.expires_at,
            request_count=endpoint.request_count,
        )
        self._session.add(row)
        await self._session.flush()

    async def find_by_token(self, token: str) -> Endpoint | None:
        stmt = select(EndpointTable).where(EndpointTable.token == token)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def find_by_id(self, endpoint_id: UUID) -> Endpoint | None:
        stmt = select(EndpointTable).where(EndpointTable.id == endpoint_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def increment_request_count(self, endpoint_id: UUID) -> None:
        stmt = (
            update(EndpointTable)
            .where(EndpointTable.id == endpoint_id)
            .values(request_count=EndpointTable.request_count + 1)
        )
        await self._session.execute(stmt)

    async def delete_expired(self) -> int:
        stmt = delete(EndpointTable).where(EndpointTable.expires_at < datetime.now(UTC))
        result = await self._session.execute(stmt)
        return result.rowcount or 0


def _to_entity(row: EndpointTable) -> Endpoint:
    return Endpoint(
        id=row.id,
        token=row.token,
        created_at=row.created_at,
        expires_at=row.expires_at,
        request_count=row.request_count,
    )
