from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from webhook_inspector.application.use_cases.list_requests import (
    EndpointNotFoundError,
    ListRequests,
)
from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.request_repository import RequestRepository


class FakeEndpointRepo(EndpointRepository):
    def __init__(self, ep=None):
        self.ep = ep

    async def save(self, e): ...
    async def find_by_token(self, t):
        return self.ep if self.ep and self.ep.token == t else None

    async def find_by_id(self, i):
        return self.ep

    async def increment_request_count(self, i): ...
    async def delete_expired(self) -> int:
        return 0

    async def count_active(self) -> int:
        return 0


class FakeRequestRepo(RequestRepository):
    def __init__(self, items):
        self.items = items

    async def save(self, r): ...
    async def find_by_id(self, i):
        return next((r for r in self.items if r.id == i), None)

    async def list_by_endpoint(self, endpoint_id, limit=50, before_id=None):
        return [r for r in self.items if r.endpoint_id == endpoint_id][:limit]


def _ep() -> Endpoint:
    return Endpoint(
        id=uuid4(),
        token="abc",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        request_count=2,
    )


async def test_list_returns_requests_for_token():
    ep = _ep()
    r1 = CapturedRequest.create(
        endpoint_id=ep.id,
        method="GET",
        path="/h/abc",
        query_string=None,
        headers={},
        body=b"",
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )
    r2 = CapturedRequest.create(
        endpoint_id=ep.id,
        method="POST",
        path="/h/abc",
        query_string=None,
        headers={},
        body=b"",
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )

    uc = ListRequests(FakeEndpointRepo(ep), FakeRequestRepo([r1, r2]))
    result = await uc.execute(token="abc", limit=50)
    assert {r.id for r in result} == {r1.id, r2.id}


async def test_list_unknown_token_raises():
    uc = ListRequests(FakeEndpointRepo(None), FakeRequestRepo([]))
    with pytest.raises(EndpointNotFoundError):
        await uc.execute(token="missing", limit=50)
