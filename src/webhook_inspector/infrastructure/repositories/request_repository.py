from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.ports.request_repository import RequestRepository
from webhook_inspector.infrastructure.database.models import RequestTable


class PostgresRequestRepository(RequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, request: CapturedRequest) -> None:
        row = RequestTable(
            id=request.id,
            endpoint_id=request.endpoint_id,
            method=request.method,
            path=request.path,
            query_string=request.query_string,
            headers=request.headers,
            body_preview=request.body_preview,
            body_size=request.body_size,
            blob_key=request.blob_key,
            source_ip=request.source_ip,
            received_at=request.received_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def find_by_id(self, request_id: UUID) -> CapturedRequest | None:
        stmt = select(RequestTable).where(RequestTable.id == request_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def list_by_endpoint(
        self,
        endpoint_id: UUID,
        limit: int = 50,
        before_id: UUID | None = None,
    ) -> list[CapturedRequest]:
        stmt = (
            select(RequestTable)
            .where(RequestTable.endpoint_id == endpoint_id)
            .order_by(RequestTable.received_at.desc(), RequestTable.id.desc())
            .limit(limit)
        )

        if before_id is not None:
            cursor = (
                await self._session.execute(
                    select(RequestTable.received_at).where(RequestTable.id == before_id)
                )
            ).scalar_one_or_none()
            if cursor is not None:
                stmt = stmt.where(RequestTable.received_at < cursor)

        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(r) for r in rows]


def _to_entity(row: RequestTable) -> CapturedRequest:
    return CapturedRequest(
        id=row.id,
        endpoint_id=row.endpoint_id,
        method=row.method,
        path=row.path,
        query_string=row.query_string,
        headers=row.headers,
        body_preview=row.body_preview,
        body_size=row.body_size,
        blob_key=row.blob_key,
        source_ip=row.source_ip,
        received_at=row.received_at,
    )
