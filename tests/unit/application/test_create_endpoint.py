from uuid import UUID

from webhook_inspector.application.use_cases.create_endpoint import CreateEndpoint
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository


class FakeEndpointRepo(EndpointRepository):
    def __init__(self):
        self.saved: list[Endpoint] = []

    async def save(self, endpoint):
        self.saved.append(endpoint)

    async def find_by_token(self, token):
        return next((e for e in self.saved if e.token == token), None)

    async def find_by_id(self, endpoint_id):
        return next((e for e in self.saved if e.id == endpoint_id), None)

    async def increment_request_count(self, endpoint_id): ...

    async def delete_expired(self) -> int:
        return 0


async def test_creates_and_persists_endpoint():
    repo = FakeEndpointRepo()
    use_case = CreateEndpoint(repo=repo, ttl_days=7)

    result = await use_case.execute()

    assert isinstance(result.id, UUID)
    assert isinstance(result.token, str)
    assert len(repo.saved) == 1
    assert repo.saved[0].token == result.token


async def test_each_call_generates_distinct_token():
    repo = FakeEndpointRepo()
    use_case = CreateEndpoint(repo=repo, ttl_days=7)

    a = await use_case.execute()
    b = await use_case.execute()

    assert a.token != b.token


async def test_creates_endpoint_with_custom_response():
    repo = FakeEndpointRepo()
    use_case = CreateEndpoint(repo=repo, ttl_days=7)

    result = await use_case.execute(
        response_status_code=201,
        response_body='{"created":true}',
        response_headers={"X-Foo": "bar"},
        response_delay_ms=100,
    )

    assert result.response_status_code == 201
    assert result.response_body == '{"created":true}'
    assert result.response_headers == {"X-Foo": "bar"}
    assert result.response_delay_ms == 100
    assert repo.saved[0].response_status_code == 201


async def test_creates_endpoint_with_default_response_when_unspecified():
    repo = FakeEndpointRepo()
    use_case = CreateEndpoint(repo=repo, ttl_days=7)

    result = await use_case.execute()  # no kwargs

    assert result.response_status_code == 200
    assert result.response_body == '{"ok":true}'
    assert result.response_headers == {}
    assert result.response_delay_ms == 0
