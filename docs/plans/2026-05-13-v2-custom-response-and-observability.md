# V2 Implementation Plan — Custom response + Copy-as-curl + Custom observability

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship V2 of webhook-inspector — endpoints with custom response (status/body/headers/latency), copy-as-curl button in viewer, custom OTEL metrics + Cloud Monitoring dashboard + 5 alerting policies — in a single monolithic PR.

**Architecture:** extend the existing Clean Architecture stack — new `Endpoint` fields + Alembic migration, new `MetricsCollector` domain port with OTEL adapter, conditional `CloudMonitoringMetricsExporter` in prod, Terraform for dashboard + alerts. No new services, no new images-per-service, just deeper instrumentation and richer endpoint config.

**Tech Stack:** Python 3.13, FastAPI, SQLModel, Alembic, OpenTelemetry, `opentelemetry-exporter-gcp-monitoring`, OpenTofu, Cloud Monitoring API. Same as Phase A/B/C — no new runtime dependency.

**Reference spec:** `~/Work/webhook-inspector/docs/specs/2026-05-13-v2-custom-response-and-observability-design.md`

---

## Conventions (apply to every task)

- **Working dir:** `~/Work/webhook-inspector` on branch `feat/v2`
- **Infra commands:** use `tofu`, never `terraform` (OpenTofu installed locally)
- **Commit messages:** Conventional Commits, no `Co-Authored-By: Claude` trailer (per `CLAUDE.md`)
- **Pre-commit hook:** runs `ruff format` + `ruff check --fix` + hygiene hooks automatically on every commit. If a hook reformats, re-stage and re-commit.
- **TDD:** RED → GREEN → COMMIT pattern. Run failing test, see it fail with the expected reason, write minimum code, see it pass, commit.
- **Tests use existing fixtures:** `session`, `engine`, `database_url` from `tests/conftest.py`, `monkeypatch` for env, `ASGITransport(app=...)` for FastAPI integration tests, `deps.get_settings.cache_clear()` + `deps._engine.cache_clear()` + `deps._session_factory.cache_clear()` before each integration test.

---

## File structure overview

```
src/webhook_inspector/
├── domain/
│   ├── entities/endpoint.py                       # MODIFY (Task 1)
│   ├── exceptions.py                              # CREATE (Task 1) — domain validation errors
│   └── ports/metrics_collector.py                 # CREATE (Task 9)
├── application/
│   └── use_cases/
│       ├── create_endpoint.py                     # MODIFY (Tasks 4, 10)
│       ├── capture_request.py                     # MODIFY (Task 10)
│       └── list_requests.py                       # unchanged
├── infrastructure/
│   ├── database/models.py                         # MODIFY (Task 2)
│   ├── repositories/endpoint_repository.py        # MODIFY (Task 3)
│   └── observability/
│       └── otel_metrics_collector.py              # CREATE (Task 9)
├── observability/
│   └── metrics.py                                 # CREATE (Task 12)
├── jobs/cleaner.py                                # MODIFY (Task 11)
└── web/
    ├── app/
    │   ├── deps.py                                # MODIFY (Tasks 5, 10, 12)
    │   ├── main.py                                # MODIFY (Task 12)
    │   ├── routes.py                              # MODIFY (Tasks 5, 8)
    │   ├── sse.py                                 # MODIFY (Task 12)
    │   └── templates/
    │       ├── landing.html                       # MODIFY (Task 7)
    │       └── request_fragment.html              # MODIFY (Task 8)
    └── ingestor/
        ├── deps.py                                # MODIFY (Task 10, 12)
        ├── main.py                                # MODIFY (Task 12)
        └── routes.py                              # MODIFY (Task 6)

migrations/versions/
└── 0002_<rev>_custom_response.py                  # CREATE (Task 2)

infra/terraform/
├── apis.tf                                        # MODIFY (Task 13)
├── service_accounts.tf                            # MODIFY (Task 13)
├── cloud_run_app.tf                               # MODIFY (Task 13)
├── cloud_run_ingestor.tf                          # MODIFY (Task 13)
├── cloud_run_cleaner.tf                           # MODIFY (Task 13)
├── cloud_run_migrator.tf                          # MODIFY (Task 13)
├── variables.tf                                   # MODIFY (Task 15)
├── monitoring_dashboard.tf                        # CREATE (Task 14)
└── monitoring_alerts.tf                           # CREATE (Task 15)

tests/
├── fakes/
│   ├── __init__.py                                # CREATE (Task 9)
│   └── metrics_collector.py                       # CREATE (Task 9)
├── unit/
│   ├── domain/
│   │   ├── test_endpoint.py                       # MODIFY (Task 1)
│   │   └── test_endpoint_response_validation.py   # CREATE (Task 1)
│   ├── application/
│   │   └── test_create_endpoint.py                # MODIFY (Task 4)
│   └── observability/
│       └── test_metrics_collector.py              # CREATE (Task 9)
└── integration/
    ├── repositories/
    │   └── test_endpoint_repository.py            # MODIFY (Task 3)
    └── web/
        ├── test_app_create_endpoint.py            # MODIFY (Task 5)
        ├── test_ingestor_capture.py               # MODIFY (Task 6)
        └── test_copy_as_curl.py                   # CREATE (Task 8)
```

---

## Task 1 — Endpoint entity custom-response fields + validation (TDD)

**Files:**
- Modify: `src/webhook_inspector/domain/entities/endpoint.py`
- Create: `src/webhook_inspector/domain/exceptions.py`
- Modify: `tests/unit/domain/test_endpoint.py`
- Create: `tests/unit/domain/test_endpoint_response_validation.py`

- [ ] **Step 1.1: Write failing tests for new validation**

Create `tests/unit/domain/test_endpoint_response_validation.py`:

```python
import pytest

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.exceptions import (
    ForbiddenResponseHeaderError,
    InvalidResponseDelayError,
    InvalidResponseStatusError,
    ResponseBodyTooLargeError,
)


def test_create_endpoint_with_defaults_keeps_v1_behavior():
    e = Endpoint.create(token="t", ttl_days=7)
    assert e.response_status_code == 200
    assert e.response_body == '{"ok":true}'
    assert e.response_headers == {}
    assert e.response_delay_ms == 0


def test_create_endpoint_accepts_custom_response_config():
    e = Endpoint.create(
        token="t",
        ttl_days=7,
        response_status_code=201,
        response_body='{"created":true}',
        response_headers={"Content-Type": "application/json"},
        response_delay_ms=500,
    )
    assert e.response_status_code == 201
    assert e.response_body == '{"created":true}'
    assert e.response_headers == {"Content-Type": "application/json"}
    assert e.response_delay_ms == 500


@pytest.mark.parametrize("status", [99, 600, -1, 0, 1000])
def test_create_endpoint_rejects_invalid_status_code(status):
    with pytest.raises(InvalidResponseStatusError):
        Endpoint.create(token="t", ttl_days=7, response_status_code=status)


@pytest.mark.parametrize("delay", [-1, 30001, 60000])
def test_create_endpoint_rejects_out_of_range_delay(delay):
    with pytest.raises(InvalidResponseDelayError):
        Endpoint.create(token="t", ttl_days=7, response_delay_ms=delay)


def test_create_endpoint_rejects_oversized_response_body():
    body = "x" * 65_537  # 64 KiB + 1
    with pytest.raises(ResponseBodyTooLargeError):
        Endpoint.create(token="t", ttl_days=7, response_body=body)


@pytest.mark.parametrize(
    "header_name",
    ["Content-Length", "content-length", "Transfer-Encoding", "Connection", "Host", "Date"],
)
def test_create_endpoint_rejects_forbidden_response_headers(header_name):
    with pytest.raises(ForbiddenResponseHeaderError):
        Endpoint.create(
            token="t", ttl_days=7, response_headers={header_name: "value"}
        )
```

- [ ] **Step 1.2: Run tests, confirm FAIL**

```bash
uv run pytest tests/unit/domain/test_endpoint_response_validation.py -v
```

Expected: `ImportError: cannot import name 'ForbiddenResponseHeaderError'` (the exceptions module doesn't exist yet).

- [ ] **Step 1.3: Create exceptions module**

Create `src/webhook_inspector/domain/exceptions.py`:

```python
"""Typed domain exceptions raised during Endpoint validation."""


class EndpointValidationError(Exception):
    """Base class for endpoint validation failures."""


class InvalidResponseStatusError(EndpointValidationError):
    """response_status_code is outside [100, 599]."""


class InvalidResponseDelayError(EndpointValidationError):
    """response_delay_ms is outside [0, 30000]."""


class ResponseBodyTooLargeError(EndpointValidationError):
    """response_body exceeds 64 KiB."""


class ForbiddenResponseHeaderError(EndpointValidationError):
    """response_headers contains a header that must be controlled by the server."""
```

- [ ] **Step 1.4: Update Endpoint entity**

Edit `src/webhook_inspector/domain/entities/endpoint.py`. Replace the entire file:

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from webhook_inspector.domain.exceptions import (
    ForbiddenResponseHeaderError,
    InvalidResponseDelayError,
    InvalidResponseStatusError,
    ResponseBodyTooLargeError,
)

_DEFAULT_RESPONSE_BODY = '{"ok":true}'
_MAX_BODY_BYTES = 65_536
_FORBIDDEN_HEADERS = frozenset(
    ["content-length", "transfer-encoding", "connection", "host", "date"]
)


@dataclass(slots=True)
class Endpoint:
    id: UUID
    token: str
    created_at: datetime
    expires_at: datetime
    request_count: int = 0
    response_status_code: int = 200
    response_body: str = _DEFAULT_RESPONSE_BODY
    response_headers: dict[str, str] = field(default_factory=dict)
    response_delay_ms: int = 0

    @classmethod
    def create(
        cls,
        token: str,
        ttl_days: int,
        *,
        response_status_code: int = 200,
        response_body: str = _DEFAULT_RESPONSE_BODY,
        response_headers: dict[str, str] | None = None,
        response_delay_ms: int = 0,
    ) -> "Endpoint":
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")

        _validate_response_status(response_status_code)
        _validate_response_delay(response_delay_ms)
        _validate_response_body_size(response_body)
        headers = response_headers or {}
        _validate_response_headers(headers)

        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            token=token,
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
            request_count=0,
            response_status_code=response_status_code,
            response_body=response_body,
            response_headers=headers,
            response_delay_ms=response_delay_ms,
        )

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


def _validate_response_status(code: int) -> None:
    if not 100 <= code <= 599:
        raise InvalidResponseStatusError(
            f"response_status_code must be in [100, 599], got {code}"
        )


def _validate_response_delay(delay_ms: int) -> None:
    if not 0 <= delay_ms <= 30_000:
        raise InvalidResponseDelayError(
            f"response_delay_ms must be in [0, 30000], got {delay_ms}"
        )


def _validate_response_body_size(body: str) -> None:
    if len(body.encode("utf-8")) > _MAX_BODY_BYTES:
        raise ResponseBodyTooLargeError(
            f"response_body exceeds {_MAX_BODY_BYTES} bytes"
        )


def _validate_response_headers(headers: dict[str, str]) -> None:
    for name in headers:
        if name.lower() in _FORBIDDEN_HEADERS:
            raise ForbiddenResponseHeaderError(
                f"header '{name}' is reserved and cannot be overridden"
            )
```

- [ ] **Step 1.5: Run tests, confirm PASS**

```bash
uv run pytest tests/unit/domain/test_endpoint_response_validation.py -v
uv run pytest tests/unit/domain/test_endpoint.py -v
uv run pytest tests/unit/ -v
```

All pass. `test_endpoint.py` continues to pass (defaults preserve V1 behavior).

- [ ] **Step 1.6: Commit**

```bash
git add src/webhook_inspector/domain/entities/endpoint.py src/webhook_inspector/domain/exceptions.py tests/unit/domain/test_endpoint_response_validation.py
git commit -m "feat(domain): add custom response fields to Endpoint with validation"
```

---

## Task 2 — SQLModel table extension + Alembic migration

**Files:**
- Modify: `src/webhook_inspector/infrastructure/database/models.py`
- Create: `migrations/versions/0002_<auto-id>_custom_response.py`

- [ ] **Step 2.1: Update EndpointTable**

Edit `src/webhook_inspector/infrastructure/database/models.py`. Add the 4 fields to `EndpointTable`:

```python
class EndpointTable(SQLModel, table=True):
    __tablename__ = "endpoints"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    token: str = Field(unique=True, index=True, nullable=False)
    created_at: datetime = Field(nullable=False)
    expires_at: datetime = Field(nullable=False, index=True)
    request_count: int = Field(default=0, nullable=False)

    # V2 — custom response
    response_status_code: int = Field(default=200, nullable=False)
    response_body: str = Field(default='{"ok":true}', nullable=False)
    response_headers: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    response_delay_ms: int = Field(default=0, nullable=False)
```

(`RequestTable` is unchanged.)

- [ ] **Step 2.2: Generate Alembic migration**

Start Postgres locally if not already running:

```bash
cd ~/Work/webhook-inspector
docker compose up -d postgres
# wait ~5s
```

Generate the migration:

```bash
uv run alembic revision --autogenerate -m "custom response"
```

A new file appears in `migrations/versions/`, named like `XYZ_custom_response.py` (rename to start with `0002_` for ordering convenience, e.g. `0002_xyz_custom_response.py`). Edit it to ensure :

- Server default for JSONB is `'{}'::jsonb` (autogen sometimes outputs `'{}'` as string).
- Server default for status_code, delay_ms, response_body are present.

Final migration content (replace the autogen body with this exact upgrade/downgrade, keeping the auto-generated `revision`, `down_revision`, etc. headers):

```python
"""custom response

Revision ID: <keep-autogen>
Revises: <keep-autogen>
Create Date: <keep-autogen>

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "<keep-autogen>"
down_revision: str | Sequence[str] | None = "19068e2673bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add custom response config to endpoints."""
    op.add_column(
        "endpoints",
        sa.Column(
            "response_status_code",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("200"),
        ),
    )
    op.add_column(
        "endpoints",
        sa.Column(
            "response_body",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{\"ok\":true}'"),
        ),
    )
    op.add_column(
        "endpoints",
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "endpoints",
        sa.Column(
            "response_delay_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Drop custom response columns."""
    op.drop_column("endpoints", "response_delay_ms")
    op.drop_column("endpoints", "response_headers")
    op.drop_column("endpoints", "response_body")
    op.drop_column("endpoints", "response_status_code")
```

- [ ] **Step 2.3: Run migration locally + verify**

```bash
uv run alembic upgrade head
docker compose exec postgres psql -U webhook -d webhook_inspector -c "\d endpoints" | grep response_
```

Expected output shows 4 columns starting with `response_`.

Test rollback works:

```bash
uv run alembic downgrade -1
docker compose exec postgres psql -U webhook -d webhook_inspector -c "\d endpoints" | grep response_
# Empty
uv run alembic upgrade head
```

- [ ] **Step 2.4: Commit**

```bash
git add migrations/versions/*custom_response.py src/webhook_inspector/infrastructure/database/models.py
git commit -m "feat(infra): add migration for endpoint custom-response columns"
```

---

## Task 3 — Repository extension (read + write new columns)

**Files:**
- Modify: `src/webhook_inspector/infrastructure/repositories/endpoint_repository.py`
- Modify: `tests/integration/repositories/test_endpoint_repository.py`

- [ ] **Step 3.1: Write failing integration test**

Append to `tests/integration/repositories/test_endpoint_repository.py`:

```python
async def test_save_and_find_persists_custom_response_fields(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(
        token="custom-resp",
        ttl_days=7,
        response_status_code=418,
        response_body='{"teapot":true}',
        response_headers={"X-Custom": "yes"},
        response_delay_ms=200,
    )
    await repo.save(endpoint)
    await session.commit()

    found = await repo.find_by_token("custom-resp")
    assert found is not None
    assert found.response_status_code == 418
    assert found.response_body == '{"teapot":true}'
    assert found.response_headers == {"X-Custom": "yes"}
    assert found.response_delay_ms == 200


async def test_save_endpoint_with_default_response(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="default-resp", ttl_days=7)
    await repo.save(endpoint)
    await session.commit()

    found = await repo.find_by_token("default-resp")
    assert found.response_status_code == 200
    assert found.response_body == '{"ok":true}'
    assert found.response_headers == {}
    assert found.response_delay_ms == 0
```

- [ ] **Step 3.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/repositories/test_endpoint_repository.py::test_save_and_find_persists_custom_response_fields -v
```

Expected: KeyError or AttributeError — the repository doesn't yet handle the new fields.

- [ ] **Step 3.3: Update repository**

Edit `src/webhook_inspector/infrastructure/repositories/endpoint_repository.py`. Find the `save` method and the `_to_entity` helper. Update both to handle the 4 new fields:

```python
async def save(self, endpoint: Endpoint) -> None:
    row = EndpointTable(
        id=endpoint.id,
        token=endpoint.token,
        created_at=endpoint.created_at,
        expires_at=endpoint.expires_at,
        request_count=endpoint.request_count,
        response_status_code=endpoint.response_status_code,
        response_body=endpoint.response_body,
        response_headers=endpoint.response_headers,
        response_delay_ms=endpoint.response_delay_ms,
    )
    self._session.add(row)
    await self._session.flush()


def _to_entity(row: EndpointTable) -> Endpoint:
    return Endpoint(
        id=row.id,
        token=row.token,
        created_at=row.created_at,
        expires_at=row.expires_at,
        request_count=row.request_count,
        response_status_code=row.response_status_code,
        response_body=row.response_body,
        response_headers=row.response_headers,
        response_delay_ms=row.response_delay_ms,
    )
```

- [ ] **Step 3.4: Run tests, confirm PASS**

```bash
uv run pytest tests/integration/repositories/test_endpoint_repository.py -v
```

All 6 tests pass (4 prior + 2 new).

- [ ] **Step 3.5: Commit**

```bash
git add src/webhook_inspector/infrastructure/repositories/endpoint_repository.py tests/integration/repositories/test_endpoint_repository.py
git commit -m "feat(infra): persist endpoint custom-response fields via PostgresEndpointRepository"
```

---

## Task 4 — CreateEndpoint use case accepts custom response

**Files:**
- Modify: `src/webhook_inspector/application/use_cases/create_endpoint.py`
- Modify: `tests/unit/application/test_create_endpoint.py`

- [ ] **Step 4.1: Write failing test**

Append to `tests/unit/application/test_create_endpoint.py`:

```python
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
```

- [ ] **Step 4.2: Run, confirm FAIL**

```bash
uv run pytest tests/unit/application/test_create_endpoint.py::test_creates_endpoint_with_custom_response -v
```

Expected: TypeError — `execute()` got unexpected keyword arguments.

- [ ] **Step 4.3: Update CreateEndpoint**

Edit `src/webhook_inspector/application/use_cases/create_endpoint.py`:

```python
from dataclasses import dataclass

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.services.token_generator import generate_token


@dataclass
class CreateEndpoint:
    repo: EndpointRepository
    ttl_days: int

    async def execute(
        self,
        *,
        response_status_code: int = 200,
        response_body: str = '{"ok":true}',
        response_headers: dict[str, str] | None = None,
        response_delay_ms: int = 0,
    ) -> Endpoint:
        endpoint = Endpoint.create(
            token=generate_token(),
            ttl_days=self.ttl_days,
            response_status_code=response_status_code,
            response_body=response_body,
            response_headers=response_headers,
            response_delay_ms=response_delay_ms,
        )
        await self.repo.save(endpoint)
        return endpoint
```

- [ ] **Step 4.4: Run, confirm PASS**

```bash
uv run pytest tests/unit/application/test_create_endpoint.py -v
```

All tests pass (existing + 2 new).

- [ ] **Step 4.5: Commit**

```bash
git add src/webhook_inspector/application/use_cases/create_endpoint.py tests/unit/application/test_create_endpoint.py
git commit -m "feat(app): CreateEndpoint accepts custom response config"
```

---

## Task 5 — POST /api/endpoints accepts custom response payload

**Files:**
- Modify: `src/webhook_inspector/web/app/routes.py`
- Modify: `tests/integration/web/test_app_create_endpoint.py`

- [ ] **Step 5.1: Write failing tests**

Append to `tests/integration/web/test_app_create_endpoint.py`:

```python
async def test_post_endpoints_with_custom_response_payload(
    monkeypatch, database_url, engine
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    payload = {
        "response": {
            "status_code": 201,
            "body": '{"created":true}',
            "headers": {"X-Foo": "bar"},
            "delay_ms": 50,
        }
    }
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/endpoints", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["response"]["status_code"] == 201
        assert data["response"]["body"] == '{"created":true}'
        assert data["response"]["headers"] == {"X-Foo": "bar"}
        assert data["response"]["delay_ms"] == 50


@pytest.mark.parametrize(
    "bad_response,expected_detail_substring",
    [
        ({"status_code": 700}, "status_code"),
        ({"delay_ms": 60000}, "delay_ms"),
        ({"body": "x" * 70000}, "body"),
        ({"headers": {"Content-Length": "0"}}, "Content-Length"),
    ],
)
async def test_post_endpoints_validation_errors(
    monkeypatch, database_url, engine, bad_response, expected_detail_substring
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/endpoints", json={"response": bad_response})
        assert resp.status_code == 400
        assert expected_detail_substring.lower() in resp.text.lower()
```

Add the import `import pytest` if not already present.

- [ ] **Step 5.2: Run, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_app_create_endpoint.py::test_post_endpoints_with_custom_response_payload -v
```

Expected: the request body is ignored or fields are missing from response.

- [ ] **Step 5.3: Update route**

Edit `src/webhook_inspector/web/app/routes.py`. Find the existing POST /api/endpoints handler. Update:

```python
from typing import Annotated

from fastapi import Body, HTTPException
from pydantic import BaseModel, Field

from webhook_inspector.domain.exceptions import (
    EndpointValidationError,
)


class CustomResponseSpec(BaseModel):
    status_code: int = 200
    body: str = '{"ok":true}'
    headers: dict[str, str] = Field(default_factory=dict)
    delay_ms: int = 0


class CreateEndpointRequest(BaseModel):
    response: CustomResponseSpec | None = None


class CreateEndpointResponse(BaseModel):
    url: str
    expires_at: str
    token: str
    response: CustomResponseSpec


@router.post("/api/endpoints", status_code=201, response_model=CreateEndpointResponse)
async def create_endpoint(
    request: Request,
    use_case: CreateEndpoint = Depends(get_create_endpoint),  # noqa: B008
    payload: Annotated[CreateEndpointRequest | None, Body()] = None,
) -> CreateEndpointResponse:
    response_spec = (payload.response if payload else None) or CustomResponseSpec()
    try:
        endpoint = await use_case.execute(
            response_status_code=response_spec.status_code,
            response_body=response_spec.body,
            response_headers=response_spec.headers,
            response_delay_ms=response_spec.delay_ms,
        )
    except EndpointValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return CreateEndpointResponse(
        url=f"{hook_base_url(request)}/h/{endpoint.token}",
        expires_at=endpoint.expires_at.isoformat(),
        token=endpoint.token,
        response=CustomResponseSpec(
            status_code=endpoint.response_status_code,
            body=endpoint.response_body,
            headers=endpoint.response_headers,
            delay_ms=endpoint.response_delay_ms,
        ),
    )
```

- [ ] **Step 5.4: Run, confirm PASS**

```bash
uv run pytest tests/integration/web/test_app_create_endpoint.py -v
```

All tests pass (existing 4 + 1 new happy + 4 parametrized validation).

- [ ] **Step 5.5: Commit**

```bash
git add src/webhook_inspector/web/app/routes.py tests/integration/web/test_app_create_endpoint.py
git commit -m "feat(web): POST /api/endpoints accepts custom response, returns 400 on invalid"
```

---

## Task 6 — Ingestor applies custom response (status/body/headers/delay)

**Files:**
- Modify: `src/webhook_inspector/web/ingestor/routes.py`
- Modify: `tests/integration/web/test_ingestor_capture.py`

- [ ] **Step 6.1: Write failing tests**

Append to `tests/integration/web/test_ingestor_capture.py`:

```python
async def test_ingestor_returns_custom_status_body_headers(
    monkeypatch, database_url, engine, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.post(
            "/api/endpoints",
            json={
                "response": {
                    "status_code": 418,
                    "body": '{"teapot":true}',
                    "headers": {"X-Custom": "yes"},
                    "delay_ms": 0,
                }
            },
        )
        token = resp.json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post(f"/h/{token}", json={"hello": "world"})
        assert resp.status_code == 418
        assert resp.json() == {"teapot": True}
        assert resp.headers.get("x-custom") == "yes"


async def test_ingestor_applies_delay(monkeypatch, database_url, engine, tmp_path):
    import time

    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.post("/api/endpoints", json={"response": {"delay_ms": 200}})
        token = resp.json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        start = time.monotonic()
        resp = await c.post(f"/h/{token}", content=b"")
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        assert elapsed >= 0.2  # at least 200ms
```

- [ ] **Step 6.2: Run, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_ingestor_capture.py::test_ingestor_returns_custom_status_body_headers -v
```

Expected: response status is 200 (the current fixed value), not 418.

- [ ] **Step 6.3: Update capture_request to return the endpoint**

Edit `src/webhook_inspector/application/use_cases/capture_request.py`. The `execute` method currently returns `CapturedRequest`. We need access to the Endpoint inside the route to read its response config. Add a returned tuple:

Find the current `execute` method. Modify the return type to `tuple[CapturedRequest, Endpoint]`:

```python
async def execute(
    self,
    token: str,
    method: str,
    path: str,
    query_string: str | None,
    headers: dict[str, str],
    body: bytes,
    source_ip: str,
) -> tuple["CapturedRequest", "Endpoint"]:  # noqa: F821 — forward ref
    endpoint = await self.endpoint_repo.find_by_token(token)
    if endpoint is None:
        raise EndpointNotFoundError(token)

    # ... existing logic ...

    return captured, endpoint
```

Add `from webhook_inspector.domain.entities.endpoint import Endpoint` if not present.

The internal tests for `CaptureRequest` may now break (they expect a single return). Update `tests/unit/application/test_capture_request.py` to unpack the tuple:

```python
# Find every `result = await uc.execute(...)` and change to:
captured, _endpoint = await uc.execute(...)
```

Run the unit test to verify the change works:

```bash
uv run pytest tests/unit/application/test_capture_request.py -v
```

All pass.

- [ ] **Step 6.4: Update ingestor route**

Edit `src/webhook_inspector/web/ingestor/routes.py`. Replace `capture()`:

```python
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from webhook_inspector.application.use_cases.capture_request import (
    CaptureRequest,
    EndpointNotFoundError,
)
from webhook_inspector.config import Settings
from webhook_inspector.web.ingestor.deps import get_capture_request, get_settings

router = APIRouter()


@router.api_route(
    "/h/{token}{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def capture(
    token: str,
    rest: str,
    request: Request,
    use_case: CaptureRequest = Depends(get_capture_request),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Response:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_body_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    try:
        _captured, endpoint = await use_case.execute(
            token=token,
            method=request.method,
            path=f"/h/{token}{rest}",
            query_string=request.url.query or None,
            headers={k.lower(): v for k, v in request.headers.items()},
            body=body,
            source_ip=request.client.host if request.client else "0.0.0.0",
        )
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    if endpoint.response_delay_ms > 0:
        await asyncio.sleep(endpoint.response_delay_ms / 1000)

    return Response(
        content=endpoint.response_body,
        status_code=endpoint.response_status_code,
        headers=endpoint.response_headers or None,
    )
```

- [ ] **Step 6.5: Run, confirm PASS**

```bash
uv run pytest tests/integration/web/test_ingestor_capture.py -v
```

All existing + 2 new tests pass.

- [ ] **Step 6.6: Commit**

```bash
git add src/webhook_inspector/application/use_cases/capture_request.py src/webhook_inspector/web/ingestor/routes.py tests/unit/application/test_capture_request.py tests/integration/web/test_ingestor_capture.py
git commit -m "feat(web): ingestor returns endpoint's custom response (status/body/headers/delay)"
```

---

## Task 7 — Landing page advanced options form

**Files:**
- Modify: `src/webhook_inspector/web/app/templates/landing.html`

- [ ] **Step 7.1: Add advanced options form to landing**

Replace the current "create button" block in `landing.html` (find the `<div class="mb-12">` containing the existing button) with:

```html
<div class="mb-12">
  <form id="create-form" class="space-y-3">
    <button
      type="submit"
      class="bg-emerald-500 hover:bg-emerald-400 text-slate-900 font-bold py-3 px-6 rounded transition-colors"
    >
      Create a webhook URL &rarr;
    </button>
    <p class="text-slate-500 text-xs">
      Click &rarr; unique URL generated &rarr; page redirects to live inspector.
    </p>

    <details class="mt-4 text-sm">
      <summary class="cursor-pointer text-slate-400 hover:text-slate-300 select-none">
        Advanced options (default: 200 OK, <code>{"ok":true}</code>, no delay)
      </summary>
      <div class="mt-3 space-y-2 bg-slate-800 p-3 rounded">
        <label class="block">
          <span class="text-slate-400 text-xs">Status code</span>
          <input id="adv-status" type="number" min="100" max="599" value="200"
                 class="block w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 mt-1 font-mono">
        </label>
        <label class="block">
          <span class="text-slate-400 text-xs">Response body</span>
          <textarea id="adv-body" rows="3"
                    class="block w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 mt-1 font-mono">{"ok":true}</textarea>
        </label>
        <label class="block">
          <span class="text-slate-400 text-xs">Headers (JSON)</span>
          <textarea id="adv-headers" rows="2" placeholder='{"Content-Type":"application/json"}'
                    class="block w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 mt-1 font-mono">{}</textarea>
        </label>
        <label class="block">
          <span class="text-slate-400 text-xs">Response delay (ms, 0-30000)</span>
          <input id="adv-delay" type="number" min="0" max="30000" value="0"
                 class="block w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 mt-1 font-mono">
        </label>
      </div>
    </details>

    <div id="create-error" class="text-rose-400 text-sm mt-2"></div>
  </form>
</div>

<script>
  document.getElementById("create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status_code = parseInt(document.getElementById("adv-status").value, 10);
    const body = document.getElementById("adv-body").value;
    const delay_ms = parseInt(document.getElementById("adv-delay").value, 10);
    let headers;
    try {
      headers = JSON.parse(document.getElementById("adv-headers").value || "{}");
    } catch {
      document.getElementById("create-error").textContent = "Headers must be valid JSON.";
      return;
    }
    const payload = { response: { status_code, body, headers, delay_ms } };

    const errEl = document.getElementById("create-error");
    errEl.textContent = "";

    try {
      const resp = await fetch("/api/endpoints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const detail = (await resp.json()).detail || resp.statusText;
        errEl.textContent = `Error: ${detail}`;
        return;
      }
      const data = await resp.json();
      window.location.href = `/${data.token}`;
    } catch (err) {
      errEl.textContent = `Network error: ${err.message}`;
    }
  });
</script>
```

The HTMX-based button is replaced with vanilla JS to avoid pulling the `htmx-ext-json-enc` extension — pragmatic for the small amount of frontend JS we have. Note `<script>` goes inside `<body>`, after the form.

- [ ] **Step 7.2: Verify locally (if Docker running)**

```bash
make up
sleep 5
open http://localhost:8000/
# Open Advanced options, set status=418, body="hi", click Create
# Should redirect to /<token>
make down
```

Skip if Docker not running. The integration test from Task 5 already exercises the API path.

- [ ] **Step 7.3: Commit**

```bash
git add src/webhook_inspector/web/app/templates/landing.html
git commit -m "feat(web): landing page advanced options for custom response"
```

---

## Task 8 — Copy-as-curl (backend list expansion + frontend button)

**Files:**
- Modify: `src/webhook_inspector/web/app/routes.py`
- Modify: `src/webhook_inspector/web/app/sse.py`
- Modify: `src/webhook_inspector/web/app/templates/request_fragment.html`
- Modify: `src/webhook_inspector/web/app/templates/viewer.html`
- Create: `tests/integration/web/test_copy_as_curl.py`

- [ ] **Step 8.1: Write failing test for the list endpoint shape**

Create `tests/integration/web/test_copy_as_curl.py`:

```python
import httpx
import pytest
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_list_requests_exposes_headers_and_body_preview(
    monkeypatch, database_url, engine, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        await c.post(
            f"/h/{token}",
            headers={"X-Test": "value", "Content-Type": "application/json"},
            content=b'{"hello":"world"}',
        )

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get(f"/api/endpoints/{token}/requests")
        items = resp.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert "headers" in item
        assert item["headers"].get("x-test") == "value"
        assert "body_preview" in item
        assert item["body_preview"] == '{"hello":"world"}'
```

- [ ] **Step 8.2: Run, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_copy_as_curl.py -v
```

Expected: KeyError — `headers` or `body_preview` not in response.

- [ ] **Step 8.3: Extend RequestItem schema**

Edit `src/webhook_inspector/web/app/routes.py`. Find `RequestItem` Pydantic model and extend:

```python
class RequestItem(BaseModel):
    id: UUID
    method: str
    path: str
    headers: dict[str, str]
    body_preview: str | None
    body_size: int
    received_at: str
```

In the `list_requests` route handler, update the conversion:

```python
return RequestList(
    items=[
        RequestItem(
            id=r.id,
            method=r.method,
            path=r.path,
            headers=r.headers,
            body_preview=r.body_preview,
            body_size=r.body_size,
            received_at=r.received_at.isoformat(),
        )
        for r in items
    ],
    next_before_id=items[-1].id if len(items) == limit else None,
)
```

- [ ] **Step 8.4: Update request_fragment.html template**

Edit `src/webhook_inspector/web/app/templates/request_fragment.html`. Replace with:

```html
<li class="border border-slate-700 rounded px-4 py-2 font-mono text-sm flex items-center gap-2"
    data-method="{{ req.method }}"
    data-url="{{ hook_url }}{{ req.path }}"
    data-headers='{{ req.headers | tojson }}'
    data-body='{{ req.body_preview | tojson if req.body_preview is not none else "null" }}'
    data-body-size="{{ req.body_size }}">
  <button type="button" class="copy-curl-btn text-slate-400 hover:text-emerald-400" aria-label="Copy as curl"
          title="Copy as curl">
    &#128203;
  </button>
  <span class="inline-block w-16 font-bold text-emerald-400">{{ req.method }}</span>
  <span class="text-slate-300">{{ req.path }}</span>
  <span class="text-slate-500 text-xs ml-2">{{ req.received_at }}</span>
  <span class="text-slate-500 text-xs ml-2">({{ req.body_size }} bytes)</span>
</li>
```

- [ ] **Step 8.5: Update viewer.html to render headers context + JS handler**

Edit `src/webhook_inspector/web/app/templates/viewer.html`. The `initial_requests` context must now include `headers`, `body_preview`, and pass `hook_url` to each fragment.

Update the route `viewer()` handler in `routes.py` — find it and replace its `context` block:

```python
return templates.TemplateResponse(
    request=request,
    name="viewer.html",
    context={
        "token": token,
        "hook_url": f"{hook_base_url(request)}/h/{token}",
        "initial_requests": [
            {
                "method": r.method,
                "path": r.path,
                "body_size": r.body_size,
                "received_at": r.received_at.isoformat(),
                "headers": r.headers,
                "body_preview": r.body_preview,
            }
            for r in initial
        ],
    },
)
```

Then in `viewer.html`, the loop already references `{% include "request_fragment.html" %}` — the new fields are available via `req`.

Update the SSE rendering in `src/webhook_inspector/web/app/sse.py` similarly — find the fragment.render call and pass the new fields:

```python
html = fragment.render(
    req={
        "method": req.method,
        "path": req.path,
        "body_size": req.body_size,
        "received_at": req.received_at.isoformat(),
        "headers": req.headers,
        "body_preview": req.body_preview,
    },
    hook_url=f"https://{request.headers.get('host', '').replace('app.', 'hook.')}/h/{token}"
    if False else "",  # placeholder, see below
)
```

**Important**: the SSE handler doesn't have `request` available because it's called from inside the streaming generator. Use a closure approach. Modify `stream_for_token` signature to accept `hook_url: str`:

```python
async def stream_for_token(
    token: str,
    session_factory: async_sessionmaker,
    notifier: PostgresNotifier,
    hook_url: str,  # NEW
) -> AsyncIterator[str]:
    ...
    async for request_id in notifier.subscribe(endpoint.id):
        ...
        html = fragment.render(
            req={
                "method": req.method,
                "path": req.path,
                "body_size": req.body_size,
                "received_at": req.received_at.isoformat(),
                "headers": req.headers,
                "body_preview": req.body_preview,
            },
            hook_url=hook_url,
        )
        ...
```

In `routes.py`, update the `sse_stream` route handler to pass `hook_url`:

```python
@router.get("/stream/{token}")
async def sse_stream(
    token: str,
    request: Request,
    notifier: PostgresNotifier = Depends(get_notifier),  # noqa: B008
):
    try:
        hook_url = f"{hook_base_url(request)}/h/{token}"
        gen = stream_for_token(token, _session_factory(), notifier, hook_url)
        first = await gen.__anext__()
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e
    ...
```

- [ ] **Step 8.6: Add JS handler in viewer.html**

In `viewer.html`, before `</body>`, append:

```html
<div id="toast" class="fixed bottom-4 right-4 bg-slate-800 text-slate-100 px-3 py-2 rounded shadow-lg opacity-0 transition-opacity pointer-events-none">
  Copied to clipboard
</div>

<script>
  function showToast() {
    const t = document.getElementById("toast");
    t.style.opacity = "1";
    setTimeout(() => { t.style.opacity = "0"; }, 2000);
  }

  function buildCurl(li) {
    const method = li.dataset.method;
    const url = li.dataset.url;
    const headers = JSON.parse(li.dataset.headers || "{}");
    const body = JSON.parse(li.dataset.body);
    const bodySize = parseInt(li.dataset.bodySize, 10);

    const lines = [`curl -X ${method} '${url.replace(/'/g, "'\\''")}'`];
    for (const [k, v] of Object.entries(headers)) {
      // Skip headers curl will set automatically
      if (["host", "content-length"].includes(k.toLowerCase())) continue;
      lines.push(`  -H '${k}: ${String(v).replace(/'/g, "'\\''")}'`);
    }
    if (body !== null && body !== "") {
      lines.push(`  -d '${body.replace(/'/g, "'\\''")}'`);
    } else if (bodySize > 8192) {
      lines.push(`  # body too large, not inline (size: ${bodySize} bytes)`);
    }
    return lines.join(" \\\n");
  }

  document.getElementById("requests").addEventListener("click", async (e) => {
    const btn = e.target.closest(".copy-curl-btn");
    if (!btn) return;
    const li = btn.closest("li");
    if (!li) return;
    const cmd = buildCurl(li);
    try {
      await navigator.clipboard.writeText(cmd);
      showToast();
    } catch {
      // Fallback for older browsers
      const ta = document.createElement("textarea");
      ta.value = cmd;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      showToast();
    }
  });
</script>
```

- [ ] **Step 8.7: Run, confirm PASS**

```bash
uv run pytest tests/integration/web/test_copy_as_curl.py -v
uv run pytest tests/integration/web/ -v
```

All integration tests pass.

- [ ] **Step 8.8: Commit**

```bash
git add src/webhook_inspector/web/app/routes.py src/webhook_inspector/web/app/sse.py src/webhook_inspector/web/app/templates/request_fragment.html src/webhook_inspector/web/app/templates/viewer.html tests/integration/web/test_copy_as_curl.py
git commit -m "feat(web): copy-as-curl button on each captured request"
```

---

## Task 9 — MetricsCollector port + OTEL adapter + Fake (TDD)

**Files:**
- Create: `src/webhook_inspector/domain/ports/metrics_collector.py`
- Create: `src/webhook_inspector/infrastructure/observability/otel_metrics_collector.py`
- Create: `src/webhook_inspector/infrastructure/observability/__init__.py`
- Create: `tests/fakes/__init__.py`
- Create: `tests/fakes/metrics_collector.py`
- Create: `tests/unit/observability/test_metrics_collector.py`

- [ ] **Step 9.1: Define the port**

Create `src/webhook_inspector/domain/ports/metrics_collector.py`:

```python
"""Port for application metrics emission. Adapter wires it to OpenTelemetry."""

from abc import ABC, abstractmethod


class MetricsCollector(ABC):
    @abstractmethod
    def endpoint_created(self) -> None: ...

    @abstractmethod
    def request_captured(
        self,
        *,
        method: str,
        body_offloaded: bool,
        body_size: int,
        duration_seconds: float,
    ) -> None: ...

    @abstractmethod
    def cleaner_run(self, deleted: int) -> None: ...
```

- [ ] **Step 9.2: Create the FakeMetricsCollector**

Create `tests/fakes/__init__.py` (empty file).

Create `tests/fakes/metrics_collector.py`:

```python
"""In-memory MetricsCollector for tests. Records every call."""

from dataclasses import dataclass, field

from webhook_inspector.domain.ports.metrics_collector import MetricsCollector


@dataclass
class CapturedCall:
    method: str
    body_offloaded: bool
    body_size: int
    duration_seconds: float


@dataclass
class FakeMetricsCollector(MetricsCollector):
    endpoints_created_count: int = 0
    captured_calls: list[CapturedCall] = field(default_factory=list)
    cleaner_runs: list[int] = field(default_factory=list)

    def endpoint_created(self) -> None:
        self.endpoints_created_count += 1

    def request_captured(
        self,
        *,
        method: str,
        body_offloaded: bool,
        body_size: int,
        duration_seconds: float,
    ) -> None:
        self.captured_calls.append(
            CapturedCall(method, body_offloaded, body_size, duration_seconds)
        )

    def cleaner_run(self, deleted: int) -> None:
        self.cleaner_runs.append(deleted)
```

- [ ] **Step 9.3: Write tests for the OTEL adapter using InMemoryMetricReader**

Create `tests/unit/observability/test_metrics_collector.py`:

```python
from opentelemetry.metrics import MeterProvider
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from webhook_inspector.infrastructure.observability.otel_metrics_collector import (
    OtelMetricsCollector,
)


def _build_collector() -> tuple[OtelMetricsCollector, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider: MeterProvider = SdkMeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    collector = OtelMetricsCollector(meter)
    return collector, reader


def _metric_data_points(reader: InMemoryMetricReader, name: str):
    metrics = reader.get_metrics_data()
    for rm in metrics.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    return list(m.data.data_points)
    return []


def test_endpoint_created_increments_counter():
    collector, reader = _build_collector()
    collector.endpoint_created()
    collector.endpoint_created()
    points = _metric_data_points(reader, "webhook_inspector.endpoints.created")
    assert sum(p.value for p in points) == 2


def test_request_captured_records_with_labels():
    collector, reader = _build_collector()
    collector.request_captured(
        method="POST", body_offloaded=False, body_size=100, duration_seconds=0.05
    )
    captured = _metric_data_points(reader, "webhook_inspector.requests.captured")
    assert any(
        p.attributes.get("method") == "POST"
        and p.attributes.get("body_offloaded") is False
        and p.value == 1
        for p in captured
    )
    body_size = _metric_data_points(reader, "webhook_inspector.requests.body_size_bytes")
    assert any(p.sum == 100 for p in body_size)
    duration = _metric_data_points(
        reader, "webhook_inspector.requests.capture_duration_seconds"
    )
    assert any(p.sum == 0.05 for p in duration)


def test_cleaner_run_emits_heartbeat_and_deletions():
    collector, reader = _build_collector()
    collector.cleaner_run(deleted=3)
    runs = _metric_data_points(reader, "webhook_inspector.cleaner.runs.completed")
    deletions = _metric_data_points(reader, "webhook_inspector.cleaner.deletions")
    assert sum(p.value for p in runs) == 1
    assert sum(p.value for p in deletions) == 3


def test_cleaner_run_with_zero_deletions_still_emits_heartbeat():
    collector, reader = _build_collector()
    collector.cleaner_run(deleted=0)
    runs = _metric_data_points(reader, "webhook_inspector.cleaner.runs.completed")
    assert sum(p.value for p in runs) == 1
```

- [ ] **Step 9.4: Run, confirm FAIL**

```bash
uv run pytest tests/unit/observability/test_metrics_collector.py -v
```

Expected: ImportError (adapter doesn't exist).

- [ ] **Step 9.5: Create the OTEL adapter**

Create `src/webhook_inspector/infrastructure/observability/__init__.py` (empty file).

Create `src/webhook_inspector/infrastructure/observability/otel_metrics_collector.py`:

```python
"""OpenTelemetry-backed MetricsCollector adapter.

Wraps an OTEL Meter. Cardinality is tightly controlled per the spec —
labels limited to `method` (uppercase HTTP verb) and `body_offloaded` (bool).
"""

from opentelemetry.metrics import Meter

from webhook_inspector.domain.ports.metrics_collector import MetricsCollector


class OtelMetricsCollector(MetricsCollector):
    def __init__(self, meter: Meter) -> None:
        self._endpoints_created = meter.create_counter(
            "webhook_inspector.endpoints.created",
            description="Total endpoints created.",
        )
        self._requests_captured = meter.create_counter(
            "webhook_inspector.requests.captured",
            description="Total webhooks captured.",
        )
        self._body_size = meter.create_histogram(
            "webhook_inspector.requests.body_size_bytes",
            description="Captured body size distribution.",
            unit="By",
        )
        self._capture_duration = meter.create_histogram(
            "webhook_inspector.requests.capture_duration_seconds",
            description="Latency from request arrival to capture commit.",
            unit="s",
        )
        self._cleaner_deletions = meter.create_counter(
            "webhook_inspector.cleaner.deletions",
            description="Endpoints deleted by the cleaner.",
        )
        # Heartbeat counter — always +1 on cleaner completion, enables
        # reliable absence-based 'cleaner stale' alerting.
        self._cleaner_runs = meter.create_counter(
            "webhook_inspector.cleaner.runs.completed",
            description="Cleaner job runs completed successfully.",
        )

    def endpoint_created(self) -> None:
        self._endpoints_created.add(1)

    def request_captured(
        self,
        *,
        method: str,
        body_offloaded: bool,
        body_size: int,
        duration_seconds: float,
    ) -> None:
        attrs = {"method": method.upper(), "body_offloaded": body_offloaded}
        self._requests_captured.add(1, attrs)
        self._body_size.record(body_size, {"body_offloaded": body_offloaded})
        self._capture_duration.record(duration_seconds, {"success": True})

    def cleaner_run(self, deleted: int) -> None:
        self._cleaner_runs.add(1)
        if deleted > 0:
            self._cleaner_deletions.add(deleted)
```

- [ ] **Step 9.6: Run, confirm PASS**

```bash
uv run pytest tests/unit/observability/test_metrics_collector.py -v
```

4 tests pass.

- [ ] **Step 9.7: Commit**

```bash
git add src/webhook_inspector/domain/ports/metrics_collector.py src/webhook_inspector/infrastructure/observability/ tests/fakes/ tests/unit/observability/test_metrics_collector.py
git commit -m "feat(obs): add MetricsCollector port + OTEL adapter + Fake for tests"
```

---

## Task 10 — Wire MetricsCollector into use cases (CreateEndpoint, CaptureRequest)

**Files:**
- Modify: `src/webhook_inspector/application/use_cases/create_endpoint.py`
- Modify: `src/webhook_inspector/application/use_cases/capture_request.py`
- Modify: `tests/unit/application/test_create_endpoint.py`
- Modify: `tests/unit/application/test_capture_request.py`
- Modify: `src/webhook_inspector/web/app/deps.py`
- Modify: `src/webhook_inspector/web/ingestor/deps.py`

- [ ] **Step 10.1: Write failing tests for metrics-wired use cases**

Append to `tests/unit/application/test_create_endpoint.py`:

```python
from tests.fakes.metrics_collector import FakeMetricsCollector


async def test_create_endpoint_increments_metric():
    repo = FakeEndpointRepo()
    metrics = FakeMetricsCollector()
    use_case = CreateEndpoint(repo=repo, ttl_days=7, metrics=metrics)

    await use_case.execute()

    assert metrics.endpoints_created_count == 1
```

Append to `tests/unit/application/test_capture_request.py`:

```python
from tests.fakes.metrics_collector import FakeMetricsCollector


async def test_capture_request_records_metric():
    ep = _make_endpoint()
    erepo = FakeEndpointRepo(ep)
    rrepo = FakeRequestRepo()
    blob = FakeBlobStorage()
    notifier = FakeNotifier()
    metrics = FakeMetricsCollector()
    uc = CaptureRequest(
        erepo, rrepo, blob, notifier,
        inline_threshold=8192,
        metrics=metrics,
    )

    await uc.execute(
        token="abc", method="POST", path="/h/abc",
        query_string=None, headers={}, body=b"hi", source_ip="192.0.2.1",
    )

    assert len(metrics.captured_calls) == 1
    call = metrics.captured_calls[0]
    assert call.method == "POST"
    assert call.body_offloaded is False
    assert call.body_size == 2
    assert call.duration_seconds >= 0
```

- [ ] **Step 10.2: Run, confirm FAIL**

```bash
uv run pytest tests/unit/application/test_create_endpoint.py::test_create_endpoint_increments_metric -v
```

Expected: TypeError — unknown kwarg `metrics`.

- [ ] **Step 10.3: Update CreateEndpoint**

Edit `src/webhook_inspector/application/use_cases/create_endpoint.py`:

```python
from dataclasses import dataclass

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.metrics_collector import MetricsCollector
from webhook_inspector.domain.services.token_generator import generate_token


@dataclass
class CreateEndpoint:
    repo: EndpointRepository
    ttl_days: int
    metrics: MetricsCollector

    async def execute(
        self,
        *,
        response_status_code: int = 200,
        response_body: str = '{"ok":true}',
        response_headers: dict[str, str] | None = None,
        response_delay_ms: int = 0,
    ) -> Endpoint:
        endpoint = Endpoint.create(
            token=generate_token(),
            ttl_days=self.ttl_days,
            response_status_code=response_status_code,
            response_body=response_body,
            response_headers=response_headers,
            response_delay_ms=response_delay_ms,
        )
        await self.repo.save(endpoint)
        self.metrics.endpoint_created()
        return endpoint
```

- [ ] **Step 10.4: Update CaptureRequest**

Edit `src/webhook_inspector/application/use_cases/capture_request.py`. Add `metrics: MetricsCollector` to the dataclass and wrap the body in timing:

```python
import logging
import time
from dataclasses import dataclass

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.metrics_collector import MetricsCollector
from webhook_inspector.domain.ports.notifier import Notifier
from webhook_inspector.domain.ports.request_repository import RequestRepository

logger = logging.getLogger(__name__)


class EndpointNotFoundError(Exception):
    pass


@dataclass
class CaptureRequest:
    endpoint_repo: EndpointRepository
    request_repo: RequestRepository
    blob_storage: BlobStorage
    notifier: Notifier
    inline_threshold: int
    metrics: MetricsCollector

    async def execute(
        self,
        token: str,
        method: str,
        path: str,
        query_string: str | None,
        headers: dict[str, str],
        body: bytes,
        source_ip: str,
    ) -> tuple[CapturedRequest, Endpoint]:
        start = time.monotonic()

        endpoint = await self.endpoint_repo.find_by_token(token)
        if endpoint is None:
            raise EndpointNotFoundError(token)

        captured = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method=method.upper(),
            path=path,
            query_string=query_string,
            headers=headers,
            body=body,
            source_ip=source_ip,
            inline_threshold_bytes=self.inline_threshold,
        )

        if captured.blob_key is not None:
            try:
                await self.blob_storage.put(captured.blob_key, body)
            except Exception:
                logger.exception("blob_storage_put_failed", extra={"key": captured.blob_key})
                captured = CapturedRequest(
                    id=captured.id,
                    endpoint_id=captured.endpoint_id,
                    method=captured.method,
                    path=captured.path,
                    query_string=captured.query_string,
                    headers=captured.headers,
                    body_preview=None,
                    body_size=captured.body_size,
                    blob_key=None,
                    source_ip=captured.source_ip,
                    received_at=captured.received_at,
                )

        await self.request_repo.save(captured)
        await self.endpoint_repo.increment_request_count(endpoint.id)
        await self.notifier.publish_new_request(endpoint.id, captured.id)

        duration = time.monotonic() - start
        self.metrics.request_captured(
            method=captured.method,
            body_offloaded=captured.blob_key is not None,
            body_size=captured.body_size,
            duration_seconds=duration,
        )

        return captured, endpoint
```

- [ ] **Step 10.5: Update existing tests that don't pass `metrics=`**

Update all calls to `CreateEndpoint(...)` and `CaptureRequest(...)` in tests :

In `tests/unit/application/test_create_endpoint.py`, every existing `CreateEndpoint(repo=repo, ttl_days=7)` becomes `CreateEndpoint(repo=repo, ttl_days=7, metrics=FakeMetricsCollector())`.

In `tests/unit/application/test_capture_request.py`, every existing `CaptureRequest(...)` constructor call gains `metrics=FakeMetricsCollector()`.

Use search-replace via your IDE or `sed`.

- [ ] **Step 10.6: Wire deps.py for both services**

Edit `src/webhook_inspector/web/app/deps.py`. Add a singleton metrics collector and pass it to `get_create_endpoint`:

```python
from functools import lru_cache

# ... existing imports ...
from webhook_inspector.application.use_cases.create_endpoint import CreateEndpoint
from webhook_inspector.domain.ports.metrics_collector import MetricsCollector


@lru_cache(maxsize=1)
def _meter():
    from opentelemetry import metrics
    return metrics.get_meter("webhook-inspector-app")


@lru_cache(maxsize=1)
def get_metrics() -> MetricsCollector:
    from webhook_inspector.infrastructure.observability.otel_metrics_collector import (
        OtelMetricsCollector,
    )
    return OtelMetricsCollector(_meter())


async def get_create_endpoint(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CreateEndpoint:
    return CreateEndpoint(
        repo=PostgresEndpointRepository(session),
        ttl_days=settings.endpoint_ttl_days,
        metrics=get_metrics(),
    )
```

Edit `src/webhook_inspector/web/ingestor/deps.py`. Same pattern for `get_capture_request`:

```python
@lru_cache(maxsize=1)
def _meter():
    from opentelemetry import metrics
    return metrics.get_meter("webhook-inspector-ingestor")


@lru_cache(maxsize=1)
def get_metrics() -> MetricsCollector:
    from webhook_inspector.infrastructure.observability.otel_metrics_collector import (
        OtelMetricsCollector,
    )
    return OtelMetricsCollector(_meter())


async def get_capture_request(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    notifier: PostgresNotifier = Depends(get_notifier),  # noqa: B008
) -> CaptureRequest:
    return CaptureRequest(
        endpoint_repo=PostgresEndpointRepository(session),
        request_repo=PostgresRequestRepository(session),
        blob_storage=_blob_storage(),
        notifier=notifier,
        inline_threshold=settings.body_inline_threshold_bytes,
        metrics=get_metrics(),
    )
```

- [ ] **Step 10.7: Run, confirm PASS**

```bash
uv run pytest tests/ -v
```

All tests pass.

- [ ] **Step 10.8: Commit**

```bash
git add src/webhook_inspector/application/use_cases/ src/webhook_inspector/web/app/deps.py src/webhook_inspector/web/ingestor/deps.py tests/unit/application/
git commit -m "feat(obs): wire MetricsCollector into CreateEndpoint and CaptureRequest"
```

---

## Task 11 — Cleaner heartbeat + deletions metric

**Files:**
- Modify: `src/webhook_inspector/jobs/cleaner.py`
- Modify: `tests/integration/test_cleaner.py`

- [ ] **Step 11.1: Write failing test**

Append to `tests/integration/test_cleaner.py`:

```python
from tests.fakes.metrics_collector import FakeMetricsCollector


async def test_cleaner_emits_heartbeat_metric_even_when_no_deletes(session_factory, database_url):
    sync_dsn = database_url.replace("+psycopg_async", "+psycopg")
    metrics = FakeMetricsCollector()

    deleted = await run_cleanup(database_url=sync_dsn, metrics=metrics)

    assert deleted == 0
    assert metrics.cleaner_runs == [0]
```

- [ ] **Step 11.2: Run, confirm FAIL**

```bash
uv run pytest tests/integration/test_cleaner.py::test_cleaner_emits_heartbeat_metric_even_when_no_deletes -v
```

Expected: TypeError — `run_cleanup` doesn't accept `metrics`.

- [ ] **Step 11.3: Update cleaner**

Edit `src/webhook_inspector/jobs/cleaner.py`:

```python
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from webhook_inspector.config import Settings
from webhook_inspector.domain.ports.metrics_collector import MetricsCollector
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


async def run_cleanup(
    database_url: str,
    metrics: MetricsCollector | None = None,
) -> int:
    url = (
        database_url.replace("postgresql+psycopg://", "postgresql+psycopg_async://")
        if "+psycopg://" in database_url
        else database_url
    )
    engine = create_async_engine(url, future=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )
    try:
        async with factory() as session:
            deleted = await PostgresEndpointRepository(session).delete_expired()
            await session.commit()
            logger.info("cleanup_complete", extra={"deleted": deleted})
            if metrics is not None:
                metrics.cleaner_run(deleted)
            return deleted
    finally:
        await engine.dispose()


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-cleaner")
    configure_tracing(
        settings.service_name + "-cleaner",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )

    # Wire metrics (lazy import — short-lived job, keep boot fast)
    from opentelemetry import metrics as otel_metrics
    from webhook_inspector.infrastructure.observability.otel_metrics_collector import (
        OtelMetricsCollector,
    )
    from webhook_inspector.observability.metrics import (
        configure_metrics,
        force_flush_metrics,
    )

    configure_metrics(
        service_name=settings.service_name + "-cleaner",
        cloud_metrics_enabled=settings.cloud_metrics_enabled,
    )
    collector = OtelMetricsCollector(otel_metrics.get_meter("webhook-inspector-cleaner"))

    try:
        deleted = asyncio.run(run_cleanup(settings.database_url, metrics=collector))
        sys.stdout.write(f"deleted {deleted} expired endpoints\n")
    finally:
        # Critical: short-lived job must flush metrics before exit.
        force_flush_metrics()


if __name__ == "__main__":
    main()
```

This file references `configure_metrics` and `force_flush_metrics` from `observability/metrics.py` — created in Task 12. The cleaner test in Step 11.1 doesn't exercise `main()`, only `run_cleanup`, so test passes before Task 12 exists.

- [ ] **Step 11.4: Run, confirm PASS**

```bash
uv run pytest tests/integration/test_cleaner.py -v
```

All 2 tests pass.

- [ ] **Step 11.5: Commit**

```bash
git add src/webhook_inspector/jobs/cleaner.py tests/integration/test_cleaner.py
git commit -m "feat(jobs): cleaner emits heartbeat + deletions metrics"
```

---

## Task 12 — `configure_metrics` + lifespan wiring + SSE counter + active endpoints gauge

**Files:**
- Create: `src/webhook_inspector/observability/metrics.py`
- Modify: `src/webhook_inspector/web/app/main.py`
- Modify: `src/webhook_inspector/web/ingestor/main.py`
- Modify: `src/webhook_inspector/web/app/sse.py`
- Modify: `src/webhook_inspector/config.py`
- Modify: `pyproject.toml`

- [ ] **Step 12.1: Add dep**

```bash
cd ~/Work/webhook-inspector
uv add opentelemetry-exporter-gcp-monitoring
```

- [ ] **Step 12.2: Settings extension**

Edit `src/webhook_inspector/config.py`. Add:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    cloud_metrics_enabled: bool = False
```

- [ ] **Step 12.3: Create `observability/metrics.py`**

Create `src/webhook_inspector/observability/metrics.py`:

```python
"""Metrics provider configuration. Mirrors the pattern in tracing.py.

In prod (CLOUD_METRICS_ENABLED=true), exports to Cloud Monitoring via
opentelemetry-exporter-gcp-monitoring (uses ADC, no manual auth).
In local/test, uses ConsoleMetricExporter (stdout) on a 60s interval.
"""

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

_provider: MeterProvider | None = None


def configure_metrics(service_name: str, cloud_metrics_enabled: bool = False) -> None:
    """Configure the global MeterProvider for the running process."""
    global _provider

    resource = Resource.create({"service.name": service_name})

    if cloud_metrics_enabled:
        from opentelemetry.exporter.cloud_monitoring import (
            CloudMonitoringMetricsExporter,
        )

        exporter = CloudMonitoringMetricsExporter()
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    else:
        exporter = ConsoleMetricExporter()
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)

    _provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_provider)


def force_flush_metrics(timeout_millis: int = 5000) -> None:
    """Flush any pending metric exports. Critical for short-lived jobs."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=timeout_millis)
```

- [ ] **Step 12.4: Wire app lifespan**

Edit `src/webhook_inspector/web/app/main.py`. Add `configure_metrics` to the lifespan:

```python
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.metrics import configure_metrics
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.app.deps import _engine
from webhook_inspector.web.app.routes import router

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-app")
    configure_tracing(
        settings.service_name + "-app",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )
    configure_metrics(
        service_name=settings.service_name + "-app",
        cloud_metrics_enabled=settings.cloud_metrics_enabled,
    )

    instrument_app(app, _engine())

    # Background task: sample active endpoints count every 60s
    task = asyncio.create_task(_active_endpoints_gauge_loop())
    try:
        yield
    finally:
        task.cancel()


async def _active_endpoints_gauge_loop() -> None:
    """Update the active endpoints gauge every 60s via direct SQL count."""
    from datetime import UTC, datetime

    from opentelemetry import metrics as otel_metrics
    from sqlalchemy import func, select

    from webhook_inspector.infrastructure.database.models import EndpointTable
    from webhook_inspector.web.app.deps import _session_factory

    meter = otel_metrics.get_meter("webhook-inspector-app")
    last_value = {"v": 0}

    def _callback(_options):  # type: ignore[no-untyped-def]
        from opentelemetry.metrics import Observation

        return [Observation(last_value["v"])]

    meter.create_observable_gauge(
        "webhook_inspector.endpoints.active",
        callbacks=[_callback],
        description="Endpoints not yet expired.",
    )

    factory = _session_factory()
    while True:
        try:
            async with factory() as s:
                row = await s.execute(
                    select(func.count(EndpointTable.id)).where(
                        EndpointTable.expires_at > datetime.now(UTC)
                    )
                )
                last_value["v"] = int(row.scalar() or 0)
        except Exception:
            pass  # quiet failure; gauge stays at previous value
        await asyncio.sleep(60)


app = FastAPI(title="Webhook Inspector — App", lifespan=lifespan)
app.state.templates = templates
app.include_router(router)
```

- [ ] **Step 12.5: Wire ingestor lifespan**

Edit `src/webhook_inspector/web/ingestor/main.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.metrics import configure_metrics
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.ingestor.deps import _engine
from webhook_inspector.web.ingestor.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-ingestor")
    configure_tracing(
        settings.service_name + "-ingestor",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )
    configure_metrics(
        service_name=settings.service_name + "-ingestor",
        cloud_metrics_enabled=settings.cloud_metrics_enabled,
    )
    instrument_app(app, _engine())
    yield


app = FastAPI(title="Webhook Inspector — Ingestor", lifespan=lifespan)
app.include_router(router)
```

- [ ] **Step 12.6: SSE active connections counter**

Edit `src/webhook_inspector/web/app/sse.py`. Add an UpDownCounter and inc/dec in the generator:

```python
from collections.abc import AsyncIterator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from opentelemetry import metrics
from sqlalchemy.ext.asyncio import async_sessionmaker

from webhook_inspector.application.use_cases.list_requests import EndpointNotFoundError
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=select_autoescape())


def _sse_counter():
    return metrics.get_meter("webhook-inspector-app").create_up_down_counter(
        "webhook_inspector.sse.active_connections",
        description="Open SSE streams.",
    )


# Module-level singleton; built lazily on first access.
_active_sse = None


def _get_active_sse():
    global _active_sse
    if _active_sse is None:
        _active_sse = _sse_counter()
    return _active_sse


async def stream_for_token(
    token: str,
    session_factory: async_sessionmaker,
    notifier: PostgresNotifier,
    hook_url: str,
) -> AsyncIterator[str]:
    async with session_factory() as session:
        endpoint = await PostgresEndpointRepository(session).find_by_token(token)
    if endpoint is None:
        raise EndpointNotFoundError(token)

    active = _get_active_sse()
    active.add(1)
    try:
        yield ": connected\n\n"

        fragment = _env.get_template("request_fragment.html")
        async for request_id in notifier.subscribe(endpoint.id):
            async with session_factory() as session:
                req = await PostgresRequestRepository(session).find_by_id(request_id)
            if req is None:
                continue
            html = fragment.render(
                req={
                    "method": req.method,
                    "path": req.path,
                    "body_size": req.body_size,
                    "received_at": req.received_at.isoformat(),
                    "headers": req.headers,
                    "body_preview": req.body_preview,
                },
                hook_url=hook_url,
            )
            encoded = "\n".join(f"data: {line}" for line in html.splitlines())
            yield f"event: message\n{encoded}\n\n"
    finally:
        active.add(-1)
```

- [ ] **Step 12.7: Run full test suite**

```bash
uv run pytest tests/ -v
uv run ruff check src tests
uv run mypy src
```

All pass. Some tests may need adjustment if they touch SSE / sse module — verify by running.

- [ ] **Step 12.8: Commit**

```bash
git add pyproject.toml uv.lock src/webhook_inspector/observability/metrics.py src/webhook_inspector/config.py src/webhook_inspector/web/app/main.py src/webhook_inspector/web/ingestor/main.py src/webhook_inspector/web/app/sse.py
git commit -m "feat(obs): configure_metrics + SSE counter + active endpoints gauge"
```

---

## Task 13 — Terraform : enable monitoring API, IAM, CLOUD_METRICS_ENABLED env

**Files:**
- Modify: `infra/terraform/apis.tf`
- Modify: `infra/terraform/service_accounts.tf`
- Modify: `infra/terraform/cloud_run_app.tf`
- Modify: `infra/terraform/cloud_run_ingestor.tf`
- Modify: `infra/terraform/cloud_run_cleaner.tf`
- Modify: `infra/terraform/cloud_run_migrator.tf`

- [ ] **Step 13.1: Add monitoring API**

Edit `infra/terraform/apis.tf`. Find the `required_apis` local list and append:

```hcl
"monitoring.googleapis.com",
```

- [ ] **Step 13.2: Add monitoring.metricWriter IAM**

Append to `infra/terraform/service_accounts.tf`:

```hcl
# Cloud Monitoring write access for runtime SAs (metrics export)
locals {
  monitoring_writer_sas = [
    google_service_account.ingestor.email,
    google_service_account.app.email,
    google_service_account.cleaner.email,
  ]
}

resource "google_project_iam_member" "monitoring_writer" {
  for_each = toset(local.monitoring_writer_sas)
  project  = var.project_id
  role     = "roles/monitoring.metricWriter"
  member   = "serviceAccount:${each.value}"
}
```

- [ ] **Step 13.3: Add CLOUD_METRICS_ENABLED env to each Cloud Run resource**

In each of the 4 files `cloud_run_app.tf`, `cloud_run_ingestor.tf`, `cloud_run_cleaner.tf`, `cloud_run_migrator.tf`, find the existing `env` block list (where `CLOUD_TRACE_ENABLED` is set) and add adjacent:

```hcl
env {
  name  = "CLOUD_METRICS_ENABLED"
  value = "true"
}
```

- [ ] **Step 13.4: Plan + commit (no apply yet, the deploy workflow will apply)**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu plan -out=plan.out
```

Expected: 1 API add + 3 IAM add + 4 env additions = 8 changes.

Skip `tofu apply` for now — push to PR, merge, and let the deploy workflow apply the Cloud Run changes. The API + IAM changes aren't in the workflow's `-target` list, so apply those manually after merge:

```bash
# After PR merge, apply the bits CI won't touch:
tofu apply -target=google_project_service.this -target=google_project_iam_member.monitoring_writer
```

- [ ] **Step 13.5: Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add infra/terraform/apis.tf infra/terraform/service_accounts.tf infra/terraform/cloud_run_app.tf infra/terraform/cloud_run_ingestor.tf infra/terraform/cloud_run_cleaner.tf infra/terraform/cloud_run_migrator.tf
git commit -m "feat(infra): enable monitoring API + IAM + CLOUD_METRICS_ENABLED env"
```

---

## Task 14 — Cloud Monitoring dashboard

**Files:**
- Create: `infra/terraform/monitoring_dashboard.tf`

- [ ] **Step 14.1: Create dashboard resource**

Create `infra/terraform/monitoring_dashboard.tf`:

```hcl
# Cloud Monitoring dashboard for webhook-inspector.
# 12 tiles in a 4×3 mosaic grid.
# Custom metrics (custom.googleapis.com/opentelemetry/...) come from the
# Python services via opentelemetry-exporter-gcp-monitoring.

resource "google_monitoring_dashboard" "main" {
  dashboard_json = jsonencode({
    displayName = "webhook-inspector"
    mosaicLayout = {
      columns = 12
      tiles = [
        # Row 1
        {
          width = 4, height = 4, xPos = 0, yPos = 0,
          widget = {
            title = "Requests captured / min"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.captured\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 0,
          widget = {
            title = "Endpoints created / min"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.endpoints.created\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 0,
          widget = {
            title = "Active endpoints"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.endpoints.active\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 2
        {
          width = 4, height = 4, xPos = 0, yPos = 4,
          widget = {
            title = "Ingest duration p50/p95/p99"
            xyChart = {
              dataSets = [
                for pct in ["50", "95", "99"] : {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.capture_duration_seconds\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_${pct}"
                      }
                    }
                  }
                  plotType   = "LINE"
                  legendTemplate = "p${pct}"
                }
              ]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 4,
          widget = {
            title = "Body size distribution (mean)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.body_size_bytes\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 4,
          widget = {
            title = "SSE active connections"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.sse.active_connections\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 3
        {
          width = 4, height = 4, xPos = 0, yPos = 8,
          widget = {
            title = "Cloud Run 5xx (ingestor)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"webhook-inspector-ingestor\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 8,
          widget = {
            title = "Cloud SQL CPU %"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 8,
          widget = {
            title = "Cloud SQL connections"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 4
        {
          width = 4, height = 4, xPos = 0, yPos = 12,
          widget = {
            title = "Cleaner deletions / day"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.cleaner.deletions\""
                    aggregation = {
                      alignmentPeriod  = "86400s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "STACKED_BAR"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 12,
          widget = {
            title = "Cloud Run instance count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/container/instance_count\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_MEAN"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["resource.label.service_name"]
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 12,
          widget = {
            title = "Log error rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/log_entry_count\" AND metric.labels.severity=\"ERROR\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        }
      ]
    }
  })
}

output "dashboard_url" {
  value = "https://console.cloud.google.com/monitoring/dashboards/builder/${basename(google_monitoring_dashboard.main.id)}?project=${var.project_id}"
}
```

- [ ] **Step 14.2: Validate locally**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu validate
tofu plan -out=plan.out
```

Expected: `1 to add`. If errors, the JSON template strings need escaping fixes — most common is unescaped quotes inside `for pct in ["50", "95", "99"]`.

- [ ] **Step 14.3: Apply (manually, since dashboard is not in deploy workflow target list)**

```bash
tofu apply -target=google_monitoring_dashboard.main
```

Visit the printed `dashboard_url` to confirm the dashboard exists. Data may be sparse for the first 60s after `tofu apply` until the next metric export.

- [ ] **Step 14.4: Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add infra/terraform/monitoring_dashboard.tf
git commit -m "feat(infra): add Cloud Monitoring dashboard with 12 tiles"
```

---

## Task 15 — Alerting policies + notification channel

**Files:**
- Modify: `infra/terraform/variables.tf`
- Create: `infra/terraform/monitoring_alerts.tf`

- [ ] **Step 15.1: Add owner_email variable**

Edit `infra/terraform/variables.tf`. Append:

```hcl
variable "owner_email" {
  type        = string
  description = "Email address that receives alert notifications."
}
```

Edit `infra/terraform/terraform.tfvars` (local, gitignored) and add :

```hcl
owner_email = "stanislas.plum@example.com"  # replace with your real email
```

- [ ] **Step 15.2: Create monitoring_alerts.tf**

Create `infra/terraform/monitoring_alerts.tf`:

```hcl
resource "google_monitoring_notification_channel" "email_owner" {
  display_name = "Owner email"
  type         = "email"
  labels = {
    email_address = var.owner_email
  }
}

# Alert 1 — High p95 ingest latency
resource "google_monitoring_alert_policy" "high_p95_latency" {
  display_name = "High p95 ingest latency"
  combiner     = "OR"
  conditions {
    display_name = "p95 > 1s for 5 min"
    condition_threshold {
      filter          = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.capture_duration_seconds\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 1.0
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
}

# Alert 2 — High 5xx rate (ingestor)
resource "google_monitoring_alert_policy" "high_5xx_rate" {
  display_name = "High 5xx rate (ingestor)"
  combiner     = "OR"
  conditions {
    display_name = "5xx rate > 5% for 5 min"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"webhook-inspector-ingestor\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.5  # raw count, not ratio; adjust after first observation
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "critical" }
}

# Alert 3 — Cloud SQL CPU
resource "google_monitoring_alert_policy" "cloudsql_cpu" {
  display_name = "Cloud SQL CPU saturated"
  combiner     = "OR"
  conditions {
    display_name = "CPU > 80% for 10 min"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
}

# Alert 4 — Cloud SQL disk
resource "google_monitoring_alert_policy" "cloudsql_disk" {
  display_name = "Cloud SQL disk pressure"
  combiner     = "OR"
  conditions {
    display_name = "Disk > 90%"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.9
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "critical" }
}

# Alert 5 — Cleaner stale (heartbeat absent)
resource "google_monitoring_alert_policy" "cleaner_stale" {
  display_name = "Cleaner job not running"
  combiner     = "OR"
  conditions {
    display_name = "No cleaner.runs.completed datapoint in 26h"
    condition_absent {
      filter   = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.cleaner.runs.completed\""
      duration = "93600s"  # 26h
      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
}
```

- [ ] **Step 15.3: Plan + apply**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu plan -out=plan.out
# Expected: 1 channel + 5 alerts = 6 to add
tofu apply plan.out
```

Confirm you receive a verification email at `owner_email` (GCP sends a one-time confirmation link). Click it to activate the channel.

- [ ] **Step 15.4: Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add infra/terraform/variables.tf infra/terraform/monitoring_alerts.tf
git commit -m "feat(infra): add 5 alerting policies + email notification channel"
```

---

## Task 16 — Documentation

**Files:**
- Modify: `README.md`
- Modify: `infra/terraform/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 16.1: Update main README**

Edit `README.md`. Add a "Custom response" section after "Production deployment", and update the roadmap row V2 to ✅ Live:

```markdown
## Custom response

By default a captured webhook gets `200 OK` with body `{"ok":true}`. You can customize this when creating an endpoint:

\`\`\`bash
curl -X POST https://app.odessa-inspect.org/api/endpoints \
  -H 'Content-Type: application/json' \
  -d '{
    "response": {
      "status_code": 201,
      "body": "{\"created\":true}",
      "headers": {"Content-Type": "application/json"},
      "delay_ms": 0
    }
  }'
\`\`\`

Constraints:
- `status_code` in `[100, 599]`
- `delay_ms` in `[0, 30000]`
- `body` up to 64 KiB
- `headers` cannot override `Content-Length`, `Transfer-Encoding`, `Connection`, `Host`, `Date`

You can also configure all of this via the landing page's "Advanced options" disclosure.
```

In the roadmap table, change the V2 row to:

```markdown
| V2 | ✅ Live | Custom response + copy-as-curl + custom OTEL metrics + Cloud Monitoring dashboards + alerting |
```

- [ ] **Step 16.2: Update infra README**

Edit `infra/terraform/README.md`. Add a "Monitoring & alerting" section before "Tearing down":

```markdown
## Monitoring & alerting

Dashboard URL (after `tofu apply`):

\`\`\`bash
cd infra/terraform
tofu output dashboard_url
\`\`\`

Alerts active :

- **High p95 ingest latency** — capture_duration p95 > 1s for 5 min
- **High 5xx rate (ingestor)** — Cloud Run 5xx requests > threshold for 5 min
- **Cloud SQL CPU saturated** — CPU > 80% for 10 min
- **Cloud SQL disk pressure** — disk > 90%
- **Cleaner stale** — no heartbeat in 26h

All routed to `owner_email` via a single notification channel.

### Manual drill

Force a 5xx surge to validate the alert :

\`\`\`bash
# Temporarily disable Cloud SQL (returns 5xx on every ingest)
gcloud sql instances patch webhook-inspector-pg-dev --activation-policy=NEVER
sleep 300  # 5 min — let the alert fire
# Check email + alert console
gcloud sql instances patch webhook-inspector-pg-dev --activation-policy=ALWAYS
\`\`\`
```

- [ ] **Step 16.3: Update CLAUDE.md**

Edit `CLAUDE.md`. Append a section before "What this project IS":

```markdown
## Metrics conventions (V2+)

- Use cases depend on `domain/ports/metrics_collector.py:MetricsCollector` ABC, never on OTEL directly.
- Adapter `infrastructure/observability/otel_metrics_collector.py` wraps the OTEL Meter.
- Cardinality is strict — labels limited to `method` (uppercase HTTP verb), `body_offloaded` (bool), `success` (bool). No label may include user-controlled values (token, IP, endpoint_id).
- New metrics go through code review : think about cardinality before adding any label.
- Short-lived jobs (cleaner, migrator) must call `force_flush_metrics()` before exit, or datapoints are lost.
- Heartbeat counters (always +1 per run) are required for absence-based alerts to work reliably.
```

- [ ] **Step 16.4: Commit**

```bash
git add README.md infra/terraform/README.md CLAUDE.md
git commit -m "docs: document V2 — custom response + monitoring + alerting"
```

---

## Self-review

(Performed by the author after writing the plan — fix inline.)

### Spec coverage

| Spec section | Task(s) |
|--------------|---------|
| Block 1 (data model + domain) | Tasks 1, 2, 3 |
| Block 2 (API) | Task 5 |
| Block 3 (Ingestor) | Task 6 |
| Block 4 (UI) | Task 7 |
| Block 5 (Copy-as-curl) | Task 8 |
| Block 6 (custom OTEL metrics) | Tasks 9, 10, 11, 12 |
| Block 7 (Terraform export wiring) | Task 13 |
| Block 8 (Dashboard) | Task 14 |
| Block 9 (Alerting) | Task 15 |
| Block 10 (Docs) | Task 16 |

### Risk register coverage

- Latency abuse → 30s cap enforced in Task 1 validation. ✓
- Cardinality explosion → label discipline encoded in Task 9 adapter signature + CLAUDE.md update in Task 16. ✓
- GCP exporter auth → Task 13 grants `monitoring.metricWriter` IAM, exporter uses ADC. ✓
- Dashboard JSON size → Task 14 keeps it under ~250 lines via uniform tile templates. ✓
- Alert false positives → 5-10 min windows. ✓
- Heartbeat counter for cleaner_stale → Task 9 (adapter) + Task 11 (wiring). ✓

### Type consistency

- `MetricsCollector` port methods : `endpoint_created()`, `request_captured(*, method, body_offloaded, body_size, duration_seconds)`, `cleaner_run(deleted)` — consistent across Tasks 9-12.
- `CustomResponseSpec` Pydantic model fields : `status_code`, `body`, `headers`, `delay_ms` — consistent in Tasks 5, 7, 8.
- `Endpoint` entity fields : `response_status_code`, `response_body`, `response_headers`, `response_delay_ms` — consistent in Tasks 1, 2, 3, 4, 6.

### Known follow-ups (not blockers for V2)

- `RequestItem.headers` exposes ALL incoming headers including potentially sensitive ones (`Authorization`, `Cookie`). For a V1-scope project this is fine (anonymous URLs are themselves the secret), but worth flagging for V5 when auth is added.
- The active endpoints gauge query runs `SELECT count(*)` every 60s. On large datasets this could be slow — currently irrelevant (table is tiny).
- Alert threshold `0.5` raw count for 5xx is a rough starting value. Tune after first 30 days.

---

## Next Steps (post-V2)

After V2 ships:

- **V3** : Forward webhook to a target URL (Pub/Sub + worker + DLQ + retry)
- **V4** : Rate limiting + Cloudflare WAF + Memorystore Redis
- **V5** : Google OAuth + claimed URLs + long-term history
- **V6** : Formal SLOs + error budgets + status page
