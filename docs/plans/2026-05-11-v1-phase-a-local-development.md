# Webhook Inspector V1 — Phase A : Local Development Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** livrer une application webhook inspector pleinement fonctionnelle en local via `docker-compose up`, capable de créer des endpoints, recevoir des webhooks, et afficher les requêtes en temps réel dans un navigateur.

**Architecture:** Clean Architecture (domain / application / infrastructure / web) en monorepo Python, deux services FastAPI (`ingestor` + `app`) + un job (`cleaner`) partageant le même package `webhook_inspector`. UI via Jinja2 + HTMX, live via Postgres LISTEN/NOTIFY + SSE.

**Tech Stack:** Python 3.13, FastAPI 0.115+, SQLModel + Alembic, Postgres 16, Jinja2, HTMX (CDN), Tailwind (CDN), pytest + testcontainers, ruff + mypy, uv (package manager), Docker + docker-compose, structlog, OpenTelemetry SDK.

**Reference spec:** `~/Work/webhook-inspector/docs/specs/2026-05-11-webhook-inspector-design.md`

**Phase A scope:** application code + tests + local Docker setup + CI lint/test workflow. **Hors scope** : Terraform, GCP, Cloudflare, déploiement prod, GCS (remplacé par stockage local).

---

## Architecture rappel

```
docker-compose
├── postgres:16              (port 5432, LISTEN/NOTIFY actif)
├── ingestor (FastAPI)       (port 8001 — ANY /h/{token})
├── app (FastAPI + Jinja2)   (port 8000 — POST /api/endpoints, GET /api/endpoints/{token}/requests, GET /{token}, GET /stream/{token})
└── cleaner (one-shot)       (lancé via `make clean` ou cron host)

blob storage : local FS (./blobs/ monté en volume) — GCS arrive en Phase B
```

## File Structure (mapping)

```
webhook-inspector/
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── Makefile
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── README.md
├── migrations/
│   ├── env.py
│   └── versions/
├── src/webhook_inspector/
│   ├── __init__.py
│   ├── config.py
│   ├── domain/
│   │   ├── entities/
│   │   │   ├── endpoint.py
│   │   │   └── captured_request.py
│   │   ├── ports/
│   │   │   ├── endpoint_repository.py
│   │   │   ├── request_repository.py
│   │   │   ├── blob_storage.py
│   │   │   └── notifier.py
│   │   └── services/
│   │       └── token_generator.py
│   ├── application/
│   │   └── use_cases/
│   │       ├── create_endpoint.py
│   │       ├── capture_request.py
│   │       └── list_requests.py
│   ├── infrastructure/
│   │   ├── database/
│   │   │   ├── models.py
│   │   │   ├── session.py
│   │   │   └── listen_notify.py
│   │   ├── repositories/
│   │   │   ├── endpoint_repository.py
│   │   │   └── request_repository.py
│   │   ├── storage/
│   │   │   └── local_blob_storage.py
│   │   └── notifications/
│   │       └── postgres_notifier.py
│   ├── web/
│   │   ├── ingestor/
│   │   │   ├── main.py
│   │   │   └── routes.py
│   │   └── app/
│   │       ├── main.py
│   │       ├── routes.py
│   │       ├── sse.py
│   │       ├── deps.py
│   │       └── templates/
│   │           ├── viewer.html
│   │           └── request_fragment.html
│   ├── jobs/
│   │   └── cleaner.py
│   └── observability/
│       ├── logging.py
│       └── tracing.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   ├── integration/
│   │   ├── repositories/
│   │   └── web/
│   └── e2e/
│       └── test_smoke.py
└── .github/workflows/
    └── lint-and-test.yml
```

## Workflow général

Chaque tâche suit le rythme **RED → GREEN → COMMIT** :
1. Écrire le test qui échoue
2. Run le test → confirmer FAIL
3. Implémenter le minimum
4. Run le test → confirmer PASS
5. Commit

**Conventional commits** : `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`, `ci:`.

---

## Task 1 : Project Bootstrap

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.pre-commit-config.yaml`, `Makefile`, `.env.example`

- [ ] **Step 1.1: Initialize uv project**

```bash
cd ~/Work/webhook-inspector
uv init --package --name webhook-inspector --python 3.13
rm -rf src/webhook_inspector/__init__.py hello.py  # cleanup
mkdir -p src/webhook_inspector/{domain/entities,domain/ports,domain/services,application/use_cases,infrastructure/database,infrastructure/repositories,infrastructure/storage,infrastructure/notifications,web/ingestor,web/app/templates,jobs,observability}
mkdir -p tests/{unit/domain,unit/application,unit/infrastructure,integration/repositories,integration/web,e2e}
mkdir -p migrations/versions
touch src/webhook_inspector/__init__.py
# Create __init__.py in every subpackage
find src/webhook_inspector -type d -exec touch {}/__init__.py \;
find tests -type d -exec touch {}/__init__.py \;
```

- [ ] **Step 1.2: Add dependencies via uv**

```bash
uv add fastapi 'uvicorn[standard]' gunicorn sqlmodel 'psycopg[binary]' alembic httpx pydantic-settings jinja2 structlog opentelemetry-distro opentelemetry-exporter-otlp opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-sqlalchemy opentelemetry-instrumentation-psycopg
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy pre-commit testcontainers
```

- [ ] **Step 1.3: Edit pyproject.toml — add ruff and mypy config**

Append to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B", "SIM"]

[tool.mypy]
python_version = "3.13"
strict = true
ignore_missing_imports = true
exclude = ["migrations/"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra --strict-markers"
```

- [ ] **Step 1.4: Create .gitignore**

Write `.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
*.egg-info/
dist/
build/
.env
.env.local
blobs/
.DS_Store
```

- [ ] **Step 1.5: Create .env.example**

Write `.env.example`:

```
DATABASE_URL=postgresql+psycopg://webhook:webhook@localhost:5432/webhook_inspector
BLOB_STORAGE_PATH=./blobs
LOG_LEVEL=INFO
ENVIRONMENT=local
SERVICE_NAME=webhook-inspector
ENDPOINT_TTL_DAYS=7
MAX_BODY_BYTES=10485760
BODY_INLINE_THRESHOLD_BYTES=8192
```

- [ ] **Step 1.6: Create Makefile**

Write `Makefile`:

```makefile
.PHONY: install lint type test test-unit test-int up down migrate clean help

install:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

type:
	uv run mypy src

test-unit:
	uv run pytest tests/unit -v

test-int:
	uv run pytest tests/integration -v

test-e2e:
	uv run pytest tests/e2e -v

test:
	uv run pytest tests -v

up:
	docker compose up -d --build

down:
	docker compose down -v

migrate:
	uv run alembic upgrade head

clean:
	uv run python -m webhook_inspector.jobs.cleaner

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
```

- [ ] **Step 1.7: Run uv sync and verify**

```bash
uv sync
uv run python -c "import fastapi, sqlmodel, structlog; print('ok')"
```

Expected: `ok`.

- [ ] **Step 1.8: Initial commit**

```bash
git add .
git commit -m "chore: scaffold project structure with uv, ruff, mypy, pytest"
```

---

## Task 2 : Domain — Endpoint entity (TDD)

**Files:**
- Create: `src/webhook_inspector/domain/entities/endpoint.py`
- Test: `tests/unit/domain/test_endpoint.py`

- [ ] **Step 2.1: Write failing test**

Create `tests/unit/domain/test_endpoint.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from webhook_inspector.domain.entities.endpoint import Endpoint


def test_create_endpoint_assigns_uuid_and_token():
    endpoint = Endpoint.create(token="abc123", ttl_days=7)

    assert isinstance(endpoint.id, UUID)
    assert endpoint.token == "abc123"
    assert endpoint.request_count == 0


def test_create_endpoint_sets_expiry_from_ttl():
    before = datetime.now(UTC)
    endpoint = Endpoint.create(token="abc123", ttl_days=7)
    after = datetime.now(UTC)

    expected_min = before + timedelta(days=7)
    expected_max = after + timedelta(days=7)
    assert expected_min <= endpoint.expires_at <= expected_max


def test_endpoint_is_expired_when_past_expiry():
    past = datetime.now(UTC) - timedelta(seconds=1)
    endpoint = Endpoint(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        token="abc",
        created_at=past - timedelta(days=7),
        expires_at=past,
        request_count=0,
    )
    assert endpoint.is_expired() is True


def test_endpoint_is_not_expired_when_future():
    future = datetime.now(UTC) + timedelta(days=1)
    endpoint = Endpoint(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        token="abc",
        created_at=datetime.now(UTC),
        expires_at=future,
        request_count=0,
    )
    assert endpoint.is_expired() is False


def test_create_endpoint_rejects_negative_ttl():
    with pytest.raises(ValueError, match="ttl_days must be positive"):
        Endpoint.create(token="abc", ttl_days=0)
```

- [ ] **Step 2.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/domain/test_endpoint.py -v
```

Expected: `ModuleNotFoundError: No module named 'webhook_inspector.domain.entities.endpoint'`.

- [ ] **Step 2.3: Implement Endpoint entity**

Create `src/webhook_inspector/domain/entities/endpoint.py`:

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4


@dataclass(slots=True)
class Endpoint:
    id: UUID
    token: str
    created_at: datetime
    expires_at: datetime
    request_count: int = 0

    @classmethod
    def create(cls, token: str, ttl_days: int) -> "Endpoint":
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            token=token,
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
            request_count=0,
        )

    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at
```

- [ ] **Step 2.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/domain/test_endpoint.py -v
```

Expected: 5 passed.

- [ ] **Step 2.5: Commit**

```bash
git add src/webhook_inspector/domain/entities/endpoint.py tests/unit/domain/test_endpoint.py
git commit -m "feat(domain): add Endpoint entity with TTL semantics"
```

---

## Task 3 : Domain — CapturedRequest entity (TDD)

**Files:**
- Create: `src/webhook_inspector/domain/entities/captured_request.py`
- Test: `tests/unit/domain/test_captured_request.py`

- [ ] **Step 3.1: Write failing test**

Create `tests/unit/domain/test_captured_request.py`:

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from webhook_inspector.domain.entities.captured_request import CapturedRequest


def test_captured_request_stores_metadata():
    endpoint_id = uuid4()
    req = CapturedRequest.create(
        endpoint_id=endpoint_id,
        method="POST",
        path="/h/abc/foo",
        query_string="x=1",
        headers={"content-type": "application/json"},
        body=b'{"hello":"world"}',
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )

    assert isinstance(req.id, UUID)
    assert req.endpoint_id == endpoint_id
    assert req.method == "POST"
    assert req.path == "/h/abc/foo"
    assert req.query_string == "x=1"
    assert req.headers == {"content-type": "application/json"}
    assert req.body_size == len(b'{"hello":"world"}')
    assert req.source_ip == "192.0.2.1"
    assert isinstance(req.received_at, datetime)
    assert req.received_at.tzinfo == UTC


def test_small_body_stays_inline():
    req = CapturedRequest.create(
        endpoint_id=uuid4(),
        method="POST",
        path="/h/abc",
        query_string=None,
        headers={},
        body=b"small",
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )

    assert req.body_preview == "small"
    assert req.blob_key is None


def test_large_body_marked_for_blob():
    big = b"x" * 9000
    req = CapturedRequest.create(
        endpoint_id=uuid4(),
        method="POST",
        path="/h/abc",
        query_string=None,
        headers={},
        body=big,
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )

    assert req.body_preview is None
    assert req.blob_key is not None
    assert str(req.id) in req.blob_key
    assert req.body_size == 9000


def test_non_utf8_body_stored_as_repr_when_inline():
    body = b"\xff\xfe\xfd"
    req = CapturedRequest.create(
        endpoint_id=uuid4(),
        method="POST",
        path="/h/abc",
        query_string=None,
        headers={},
        body=body,
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )

    assert req.body_preview is not None
    assert "\\x" in req.body_preview


def test_method_must_be_uppercase():
    with pytest.raises(ValueError, match="method must be uppercase"):
        CapturedRequest.create(
            endpoint_id=uuid4(),
            method="post",
            path="/h/abc",
            query_string=None,
            headers={},
            body=b"",
            source_ip="192.0.2.1",
            inline_threshold_bytes=8192,
        )
```

- [ ] **Step 3.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/domain/test_captured_request.py -v
```

Expected: import error.

- [ ] **Step 3.3: Implement CapturedRequest**

Create `src/webhook_inspector/domain/entities/captured_request.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(slots=True)
class CapturedRequest:
    id: UUID
    endpoint_id: UUID
    method: str
    path: str
    query_string: str | None
    headers: dict[str, str]
    body_preview: str | None
    body_size: int
    blob_key: str | None
    source_ip: str
    received_at: datetime

    @classmethod
    def create(
        cls,
        endpoint_id: UUID,
        method: str,
        path: str,
        query_string: str | None,
        headers: dict[str, str],
        body: bytes,
        source_ip: str,
        inline_threshold_bytes: int,
    ) -> "CapturedRequest":
        if method != method.upper():
            raise ValueError("method must be uppercase")

        request_id = uuid4()
        body_size = len(body)

        if body_size <= inline_threshold_bytes:
            preview = _decode_body_safe(body)
            blob_key = None
        else:
            preview = None
            blob_key = f"{endpoint_id}/{request_id}"

        return cls(
            id=request_id,
            endpoint_id=endpoint_id,
            method=method,
            path=path,
            query_string=query_string,
            headers=headers,
            body_preview=preview,
            body_size=body_size,
            blob_key=blob_key,
            source_ip=source_ip,
            received_at=datetime.now(UTC),
        )


def _decode_body_safe(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return repr(body)[2:-1]  # strip b'' wrapper
```

- [ ] **Step 3.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/domain/test_captured_request.py -v
```

Expected: 5 passed.

- [ ] **Step 3.5: Commit**

```bash
git add src/webhook_inspector/domain/entities/captured_request.py tests/unit/domain/test_captured_request.py
git commit -m "feat(domain): add CapturedRequest entity with body offload threshold"
```

---

## Task 4 : Domain — Token generator (TDD)

**Files:**
- Create: `src/webhook_inspector/domain/services/token_generator.py`
- Test: `tests/unit/domain/test_token_generator.py`

- [ ] **Step 4.1: Write failing test**

Create `tests/unit/domain/test_token_generator.py`:

```python
import re

from webhook_inspector.domain.services.token_generator import generate_token


def test_token_is_url_safe_string():
    token = generate_token()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_token_has_at_least_128_bits_of_entropy():
    # 16 bytes urlsafe → 22 chars sans padding
    token = generate_token()
    assert len(token) >= 22


def test_tokens_are_unique_across_calls():
    tokens = {generate_token() for _ in range(1000)}
    assert len(tokens) == 1000
```

- [ ] **Step 4.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/domain/test_token_generator.py -v
```

Expected: import error.

- [ ] **Step 4.3: Implement token_generator**

Create `src/webhook_inspector/domain/services/token_generator.py`:

```python
import secrets


def generate_token() -> str:
    """Generate a URL-safe token with 128 bits of entropy."""
    return secrets.token_urlsafe(16)
```

- [ ] **Step 4.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/domain/test_token_generator.py -v
```

Expected: 3 passed.

- [ ] **Step 4.5: Commit**

```bash
git add src/webhook_inspector/domain/services/token_generator.py tests/unit/domain/test_token_generator.py
git commit -m "feat(domain): add token_generator service"
```

---

## Task 5 : Domain — Repository ports (interfaces)

**Files:**
- Create: `src/webhook_inspector/domain/ports/endpoint_repository.py`, `src/webhook_inspector/domain/ports/request_repository.py`, `src/webhook_inspector/domain/ports/blob_storage.py`, `src/webhook_inspector/domain/ports/notifier.py`

Pas de test direct sur les interfaces (elles seront testées via les use cases).

- [ ] **Step 5.1: Create endpoint_repository port**

Create `src/webhook_inspector/domain/ports/endpoint_repository.py`:

```python
from abc import ABC, abstractmethod
from uuid import UUID

from webhook_inspector.domain.entities.endpoint import Endpoint


class EndpointRepository(ABC):
    @abstractmethod
    async def save(self, endpoint: Endpoint) -> None: ...

    @abstractmethod
    async def find_by_token(self, token: str) -> Endpoint | None: ...

    @abstractmethod
    async def find_by_id(self, endpoint_id: UUID) -> Endpoint | None: ...

    @abstractmethod
    async def increment_request_count(self, endpoint_id: UUID) -> None: ...

    @abstractmethod
    async def delete_expired(self) -> int:
        """Delete expired endpoints. Returns count of deleted rows."""
```

- [ ] **Step 5.2: Create request_repository port**

Create `src/webhook_inspector/domain/ports/request_repository.py`:

```python
from abc import ABC, abstractmethod
from uuid import UUID

from webhook_inspector.domain.entities.captured_request import CapturedRequest


class RequestRepository(ABC):
    @abstractmethod
    async def save(self, request: CapturedRequest) -> None: ...

    @abstractmethod
    async def find_by_id(self, request_id: UUID) -> CapturedRequest | None: ...

    @abstractmethod
    async def list_by_endpoint(
        self,
        endpoint_id: UUID,
        limit: int = 50,
        before_id: UUID | None = None,
    ) -> list[CapturedRequest]: ...
```

- [ ] **Step 5.3: Create blob_storage port**

Create `src/webhook_inspector/domain/ports/blob_storage.py`:

```python
from abc import ABC, abstractmethod


class BlobStorage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...
```

- [ ] **Step 5.4: Create notifier port**

Create `src/webhook_inspector/domain/ports/notifier.py`:

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID


class Notifier(ABC):
    @abstractmethod
    async def publish_new_request(self, endpoint_id: UUID, request_id: UUID) -> None: ...

    @abstractmethod
    def subscribe(self, endpoint_id: UUID) -> AsyncIterator[UUID]:
        """Yields request_id values for each new request on the endpoint."""
```

- [ ] **Step 5.5: Verify no runtime errors via import**

```bash
uv run python -c "from webhook_inspector.domain.ports import endpoint_repository, request_repository, blob_storage, notifier; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5.6: Commit**

```bash
git add src/webhook_inspector/domain/ports/
git commit -m "feat(domain): define repository, storage, and notifier ports"
```

---

## Task 6 : Configuration loader (Pydantic Settings)

**Files:**
- Create: `src/webhook_inspector/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 6.1: Write failing test**

Create `tests/unit/test_config.py`:

```python
import os
from unittest.mock import patch

from webhook_inspector.config import Settings


def test_settings_read_from_env():
    env = {
        "DATABASE_URL": "postgresql+psycopg://u:p@h:5432/db",
        "BLOB_STORAGE_PATH": "/tmp/blobs",
        "ENDPOINT_TTL_DAYS": "7",
        "MAX_BODY_BYTES": "1048576",
        "BODY_INLINE_THRESHOLD_BYTES": "4096",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
        assert s.blob_storage_path == "/tmp/blobs"
        assert s.endpoint_ttl_days == 7
        assert s.max_body_bytes == 1048576
        assert s.body_inline_threshold_bytes == 4096


def test_settings_have_sensible_defaults_for_local():
    env = {"DATABASE_URL": "postgresql+psycopg://u:p@h:5432/db"}
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
        assert s.endpoint_ttl_days == 7
        assert s.max_body_bytes == 10 * 1024 * 1024
        assert s.body_inline_threshold_bytes == 8 * 1024
        assert s.environment == "local"
```

- [ ] **Step 6.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: import error.

- [ ] **Step 6.3: Implement Settings**

Create `src/webhook_inspector/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    blob_storage_path: str = "./blobs"
    endpoint_ttl_days: int = 7
    max_body_bytes: int = 10 * 1024 * 1024
    body_inline_threshold_bytes: int = 8 * 1024
    environment: str = "local"
    service_name: str = "webhook-inspector"
    log_level: str = "INFO"
```

- [ ] **Step 6.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 6.5: Commit**

```bash
git add src/webhook_inspector/config.py tests/unit/test_config.py
git commit -m "feat(config): add Pydantic Settings loader"
```

---

## Task 7 : Infrastructure — SQLModel tables + Alembic baseline

**Files:**
- Create: `src/webhook_inspector/infrastructure/database/models.py`
- Create: `src/webhook_inspector/infrastructure/database/session.py`
- Create: `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`

- [ ] **Step 7.1: Create SQLModel table classes**

Create `src/webhook_inspector/infrastructure/database/models.py`:

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlmodel import Field, SQLModel


class EndpointTable(SQLModel, table=True):
    __tablename__ = "endpoints"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    token: str = Field(unique=True, index=True, nullable=False)
    created_at: datetime = Field(nullable=False)
    expires_at: datetime = Field(nullable=False, index=True)
    request_count: int = Field(default=0, nullable=False)


class RequestTable(SQLModel, table=True):
    __tablename__ = "requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    endpoint_id: UUID = Field(foreign_key="endpoints.id", nullable=False, index=True)
    method: str = Field(nullable=False)
    path: str = Field(nullable=False)
    query_string: str | None = Field(default=None)
    headers: dict = Field(sa_column=Column(JSONB, nullable=False))
    body_preview: str | None = Field(default=None)
    body_size: int = Field(nullable=False)
    blob_key: str | None = Field(default=None)
    source_ip: str = Field(sa_column=Column(INET, nullable=False))
    received_at: datetime = Field(nullable=False)
```

- [ ] **Step 7.2: Create async session factory**

Create `src/webhook_inspector/infrastructure/database/session.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from webhook_inspector.config import Settings


def make_engine(settings: Settings):
    # Convert sync URL to async if needed
    url = settings.database_url.replace(
        "postgresql+psycopg://", "postgresql+psycopg_async://"
    ) if "+psycopg://" in settings.database_url else settings.database_url
    return create_async_engine(url, pool_pre_ping=True, future=True)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 7.3: Initialize Alembic**

```bash
uv run alembic init -t async migrations
```

Note: Alembic crée le dossier `migrations/`. Si ce dossier existe déjà, supprime-le avant.

- [ ] **Step 7.4: Configure migrations/env.py**

Replace `migrations/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context
from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.database import models  # noqa: F401  - register tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace(
    "postgresql+psycopg://", "postgresql+psycopg_async://"
))

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 7.5: Start a local Postgres for autogen**

Create a minimal `docker-compose.yml` (will be extended later):

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: webhook
      POSTGRES_PASSWORD: webhook
      POSTGRES_DB: webhook_inspector
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U webhook"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

```bash
docker compose up -d postgres
cp .env.example .env
```

- [ ] **Step 7.6: Generate initial migration**

```bash
uv run alembic revision --autogenerate -m "initial schema"
```

Verify the file in `migrations/versions/` creates `endpoints` and `requests` tables. If the autogen misses the JSONB or INET columns, edit manually:

```python
sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
sa.Column("source_ip", postgresql.INET(), nullable=False),
```

(import `from sqlalchemy.dialects import postgresql`).

- [ ] **Step 7.7: Run migration to verify**

```bash
uv run alembic upgrade head
```

Connect to Postgres and check tables exist:

```bash
docker compose exec postgres psql -U webhook -d webhook_inspector -c "\dt"
```

Expected: `endpoints`, `requests`, `alembic_version`.

- [ ] **Step 7.8: Commit**

```bash
git add alembic.ini migrations/ src/webhook_inspector/infrastructure/database/ docker-compose.yml
git commit -m "feat(infra): add SQLModel tables and Alembic baseline migration"
```

---

## Task 8 : Infrastructure — EndpointRepository (integration test)

**Files:**
- Create: `src/webhook_inspector/infrastructure/repositories/endpoint_repository.py`
- Test: `tests/integration/repositories/test_endpoint_repository.py`
- Create: `tests/conftest.py`

- [ ] **Step 8.1: Create shared pytest fixtures**

Create `tests/conftest.py`:

```python
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
    return postgres_container.get_connection_url().replace(
        "postgresql+psycopg://", "postgresql+psycopg_async://"
    )


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
```

- [ ] **Step 8.2: Write failing integration test**

Create `tests/integration/repositories/test_endpoint_repository.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)


async def test_save_and_find_by_token(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="abc123", ttl_days=7)

    await repo.save(endpoint)
    await session.commit()

    found = await repo.find_by_token("abc123")
    assert found is not None
    assert found.id == endpoint.id
    assert found.token == "abc123"
    assert found.request_count == 0


async def test_find_by_token_returns_none_when_missing(session):
    repo = PostgresEndpointRepository(session)
    assert await repo.find_by_token("unknown") is None


async def test_increment_request_count(session):
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="abc", ttl_days=7)
    await repo.save(endpoint)
    await session.commit()

    await repo.increment_request_count(endpoint.id)
    await repo.increment_request_count(endpoint.id)
    await session.commit()

    found = await repo.find_by_token("abc")
    assert found.request_count == 2


async def test_delete_expired_removes_only_expired(session):
    repo = PostgresEndpointRepository(session)
    fresh = Endpoint.create(token="fresh", ttl_days=7)
    stale = Endpoint(
        id=uuid4(),
        token="stale",
        created_at=datetime.now(UTC) - timedelta(days=10),
        expires_at=datetime.now(UTC) - timedelta(days=3),
        request_count=0,
    )
    await repo.save(fresh)
    await repo.save(stale)
    await session.commit()

    deleted = await repo.delete_expired()
    await session.commit()

    assert deleted == 1
    assert await repo.find_by_token("fresh") is not None
    assert await repo.find_by_token("stale") is None
```

- [ ] **Step 8.3: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/repositories/test_endpoint_repository.py -v
```

Expected: import error.

- [ ] **Step 8.4: Implement PostgresEndpointRepository**

Create `src/webhook_inspector/infrastructure/repositories/endpoint_repository.py`:

```python
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
```

- [ ] **Step 8.5: Run test, confirm PASS**

```bash
uv run pytest tests/integration/repositories/test_endpoint_repository.py -v
```

Expected: 4 passed.

- [ ] **Step 8.6: Commit**

```bash
git add src/webhook_inspector/infrastructure/repositories/endpoint_repository.py tests/integration/ tests/conftest.py
git commit -m "feat(infra): add PostgresEndpointRepository with integration tests"
```

---

## Task 9 : Infrastructure — RequestRepository (integration test)

**Files:**
- Create: `src/webhook_inspector/infrastructure/repositories/request_repository.py`
- Test: `tests/integration/repositories/test_request_repository.py`

- [ ] **Step 9.1: Write failing integration test**

Create `tests/integration/repositories/test_request_repository.py`:

```python
from uuid import uuid4

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)


async def _seed_endpoint(session) -> Endpoint:
    repo = PostgresEndpointRepository(session)
    endpoint = Endpoint.create(token="abc", ttl_days=7)
    await repo.save(endpoint)
    await session.commit()
    return endpoint


async def test_save_and_find_by_id(session):
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    req = CapturedRequest.create(
        endpoint_id=endpoint.id,
        method="POST",
        path="/h/abc",
        query_string=None,
        headers={"x-key": "v"},
        body=b'{"a":1}',
        source_ip="192.0.2.1",
        inline_threshold_bytes=8192,
    )
    await repo.save(req)
    await session.commit()

    found = await repo.find_by_id(req.id)
    assert found is not None
    assert found.endpoint_id == endpoint.id
    assert found.method == "POST"
    assert found.headers == {"x-key": "v"}
    assert found.body_preview == '{"a":1}'


async def test_list_by_endpoint_returns_newest_first(session):
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)

    ids = []
    for i in range(3):
        req = CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="GET",
            path=f"/h/abc/{i}",
            query_string=None,
            headers={},
            body=b"",
            source_ip="192.0.2.1",
            inline_threshold_bytes=8192,
        )
        await repo.save(req)
        ids.append(req.id)
    await session.commit()

    result = await repo.list_by_endpoint(endpoint.id, limit=10)
    assert len(result) == 3
    assert [r.id for r in result] == list(reversed(ids))


async def test_list_by_endpoint_respects_limit(session):
    endpoint = await _seed_endpoint(session)
    repo = PostgresRequestRepository(session)
    for i in range(5):
        await repo.save(CapturedRequest.create(
            endpoint_id=endpoint.id,
            method="GET",
            path=f"/h/abc/{i}",
            query_string=None,
            headers={},
            body=b"",
            source_ip="192.0.2.1",
            inline_threshold_bytes=8192,
        ))
    await session.commit()

    result = await repo.list_by_endpoint(endpoint.id, limit=2)
    assert len(result) == 2


async def test_find_by_id_returns_none_when_missing(session):
    repo = PostgresRequestRepository(session)
    assert await repo.find_by_id(uuid4()) is None
```

- [ ] **Step 9.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/repositories/test_request_repository.py -v
```

Expected: import error.

- [ ] **Step 9.3: Implement PostgresRequestRepository**

Create `src/webhook_inspector/infrastructure/repositories/request_repository.py`:

```python
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
```

- [ ] **Step 9.4: Run test, confirm PASS**

```bash
uv run pytest tests/integration/repositories/test_request_repository.py -v
```

Expected: 4 passed.

- [ ] **Step 9.5: Commit**

```bash
git add src/webhook_inspector/infrastructure/repositories/request_repository.py tests/integration/repositories/test_request_repository.py
git commit -m "feat(infra): add PostgresRequestRepository with newest-first listing"
```

---

## Task 10 : Infrastructure — Local BlobStorage adapter

**Files:**
- Create: `src/webhook_inspector/infrastructure/storage/local_blob_storage.py`
- Test: `tests/unit/infrastructure/test_local_blob_storage.py`

- [ ] **Step 10.1: Write failing test**

Create `tests/unit/infrastructure/test_local_blob_storage.py`:

```python
from pathlib import Path

import pytest

from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalBlobStorage:
    return LocalBlobStorage(base_path=str(tmp_path))


async def test_put_then_get_roundtrip(storage):
    await storage.put("abc/def", b"hello world")
    assert await storage.get("abc/def") == b"hello world"


async def test_get_missing_returns_none(storage):
    assert await storage.get("nope/nope") is None


async def test_put_creates_intermediate_dirs(storage, tmp_path):
    await storage.put("a/b/c/d.bin", b"data")
    assert (tmp_path / "a" / "b" / "c" / "d.bin").exists()


async def test_put_rejects_path_traversal(storage):
    with pytest.raises(ValueError, match="invalid key"):
        await storage.put("../escape", b"x")
```

- [ ] **Step 10.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/infrastructure/test_local_blob_storage.py -v
```

Expected: import error.

- [ ] **Step 10.3: Implement LocalBlobStorage**

Create `src/webhook_inspector/infrastructure/storage/local_blob_storage.py`:

```python
import asyncio
from pathlib import Path

from webhook_inspector.domain.ports.blob_storage import BlobStorage


class LocalBlobStorage(BlobStorage):
    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: bytes) -> None:
        target = self._resolve_safe(key)
        await asyncio.to_thread(self._write, target, data)

    async def get(self, key: str) -> bytes | None:
        target = self._resolve_safe(key)
        if not target.exists():
            return None
        return await asyncio.to_thread(target.read_bytes)

    def _resolve_safe(self, key: str) -> Path:
        target = (self._base / key).resolve()
        if not str(target).startswith(str(self._base)):
            raise ValueError(f"invalid key: {key!r}")
        return target

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
```

- [ ] **Step 10.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/infrastructure/test_local_blob_storage.py -v
```

Expected: 4 passed.

- [ ] **Step 10.5: Commit**

```bash
git add src/webhook_inspector/infrastructure/storage/local_blob_storage.py tests/unit/infrastructure/
git commit -m "feat(infra): add LocalBlobStorage for dev"
```

---

## Task 11 : Application — CreateEndpoint use case

**Files:**
- Create: `src/webhook_inspector/application/use_cases/create_endpoint.py`
- Test: `tests/unit/application/test_create_endpoint.py`

- [ ] **Step 11.1: Write failing test with fake repo**

Create `tests/unit/application/test_create_endpoint.py`:

```python
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

    async def delete_expired(self) -> int: return 0


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
```

- [ ] **Step 11.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/application/test_create_endpoint.py -v
```

Expected: import error.

- [ ] **Step 11.3: Implement CreateEndpoint**

Create `src/webhook_inspector/application/use_cases/create_endpoint.py`:

```python
from dataclasses import dataclass

from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.services.token_generator import generate_token


@dataclass
class CreateEndpoint:
    repo: EndpointRepository
    ttl_days: int

    async def execute(self) -> Endpoint:
        endpoint = Endpoint.create(token=generate_token(), ttl_days=self.ttl_days)
        await self.repo.save(endpoint)
        return endpoint
```

- [ ] **Step 11.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/application/test_create_endpoint.py -v
```

Expected: 2 passed.

- [ ] **Step 11.5: Commit**

```bash
git add src/webhook_inspector/application/use_cases/create_endpoint.py tests/unit/application/test_create_endpoint.py
git commit -m "feat(app): add CreateEndpoint use case"
```

---

## Task 12 : Application — CaptureRequest use case

**Files:**
- Create: `src/webhook_inspector/application/use_cases/capture_request.py`
- Test: `tests/unit/application/test_capture_request.py`

This use case orchestrates: lookup endpoint, optionally offload body, save request, increment counter, publish notification. Errors in blob storage are best-effort.

- [ ] **Step 12.1: Write failing test**

Create `tests/unit/application/test_capture_request.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from webhook_inspector.application.use_cases.capture_request import (
    CaptureRequest,
    EndpointNotFoundError,
)
from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.entities.endpoint import Endpoint
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.notifier import Notifier
from webhook_inspector.domain.ports.request_repository import RequestRepository


class FakeEndpointRepo(EndpointRepository):
    def __init__(self, seed: Endpoint | None = None):
        self.saved = [seed] if seed else []
        self.increments: list[UUID] = []

    async def save(self, endpoint): self.saved.append(endpoint)
    async def find_by_token(self, token): return next((e for e in self.saved if e.token == token), None)
    async def find_by_id(self, endpoint_id): return next((e for e in self.saved if e.id == endpoint_id), None)
    async def increment_request_count(self, endpoint_id): self.increments.append(endpoint_id)
    async def delete_expired(self) -> int: return 0


class FakeRequestRepo(RequestRepository):
    def __init__(self): self.saved: list[CapturedRequest] = []
    async def save(self, request): self.saved.append(request)
    async def find_by_id(self, request_id): return next((r for r in self.saved if r.id == request_id), None)
    async def list_by_endpoint(self, endpoint_id, limit=50, before_id=None): return []


class FakeBlobStorage(BlobStorage):
    def __init__(self, fail: bool = False):
        self.puts: dict[str, bytes] = {}
        self.fail = fail
    async def put(self, key, data):
        if self.fail:
            raise RuntimeError("storage down")
        self.puts[key] = data
    async def get(self, key): return self.puts.get(key)


class FakeNotifier(Notifier):
    def __init__(self): self.published: list[tuple[UUID, UUID]] = []
    async def publish_new_request(self, endpoint_id, request_id):
        self.published.append((endpoint_id, request_id))
    def subscribe(self, endpoint_id): raise NotImplementedError


def _make_endpoint() -> Endpoint:
    return Endpoint(
        id=uuid4(),
        token="abc",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        request_count=0,
    )


async def test_capture_small_body_inline():
    ep = _make_endpoint()
    erepo = FakeEndpointRepo(ep)
    rrepo = FakeRequestRepo()
    blob = FakeBlobStorage()
    notifier = FakeNotifier()
    uc = CaptureRequest(erepo, rrepo, blob, notifier, inline_threshold=8192)

    saved = await uc.execute(
        token="abc", method="POST", path="/h/abc",
        query_string=None, headers={"x": "y"},
        body=b"hi", source_ip="192.0.2.1",
    )

    assert len(rrepo.saved) == 1
    assert rrepo.saved[0].body_preview == "hi"
    assert rrepo.saved[0].blob_key is None
    assert blob.puts == {}
    assert erepo.increments == [ep.id]
    assert notifier.published == [(ep.id, saved.id)]


async def test_capture_large_body_uploads_blob():
    ep = _make_endpoint()
    erepo = FakeEndpointRepo(ep)
    rrepo = FakeRequestRepo()
    blob = FakeBlobStorage()
    notifier = FakeNotifier()
    uc = CaptureRequest(erepo, rrepo, blob, notifier, inline_threshold=8192)

    big = b"x" * 10000
    saved = await uc.execute(
        token="abc", method="POST", path="/h/abc",
        query_string=None, headers={}, body=big, source_ip="192.0.2.1",
    )

    assert saved.blob_key is not None
    assert blob.puts[saved.blob_key] == big


async def test_capture_falls_back_when_blob_storage_fails():
    ep = _make_endpoint()
    erepo = FakeEndpointRepo(ep)
    rrepo = FakeRequestRepo()
    blob = FakeBlobStorage(fail=True)
    notifier = FakeNotifier()
    uc = CaptureRequest(erepo, rrepo, blob, notifier, inline_threshold=8192)

    big = b"x" * 10000
    saved = await uc.execute(
        token="abc", method="POST", path="/h/abc",
        query_string=None, headers={}, body=big, source_ip="192.0.2.1",
    )

    # Metadata persisted even though blob failed
    assert len(rrepo.saved) == 1
    assert saved.blob_key is None  # downgraded
    assert saved.body_size == 10000


async def test_capture_unknown_token_raises():
    erepo = FakeEndpointRepo()
    rrepo = FakeRequestRepo()
    blob = FakeBlobStorage()
    notifier = FakeNotifier()
    uc = CaptureRequest(erepo, rrepo, blob, notifier, inline_threshold=8192)

    with pytest.raises(EndpointNotFoundError):
        await uc.execute(
            token="missing", method="GET", path="/h/missing",
            query_string=None, headers={}, body=b"", source_ip="192.0.2.1",
        )


async def test_capture_uppercases_method():
    ep = _make_endpoint()
    erepo = FakeEndpointRepo(ep)
    rrepo = FakeRequestRepo()
    blob = FakeBlobStorage()
    notifier = FakeNotifier()
    uc = CaptureRequest(erepo, rrepo, blob, notifier, inline_threshold=8192)

    saved = await uc.execute(
        token="abc", method="post", path="/h/abc",
        query_string=None, headers={}, body=b"", source_ip="192.0.2.1",
    )

    assert saved.method == "POST"
```

- [ ] **Step 12.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/application/test_capture_request.py -v
```

Expected: import error.

- [ ] **Step 12.3: Implement CaptureRequest**

Create `src/webhook_inspector/application/use_cases/capture_request.py`:

```python
import logging
from dataclasses import dataclass

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
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

    async def execute(
        self,
        token: str,
        method: str,
        path: str,
        query_string: str | None,
        headers: dict[str, str],
        body: bytes,
        source_ip: str,
    ) -> CapturedRequest:
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
                # Downgrade: drop blob reference; keep metadata
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

        return captured
```

- [ ] **Step 12.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/application/test_capture_request.py -v
```

Expected: 5 passed.

- [ ] **Step 12.5: Commit**

```bash
git add src/webhook_inspector/application/use_cases/capture_request.py tests/unit/application/test_capture_request.py
git commit -m "feat(app): add CaptureRequest use case with blob offload + degradation"
```

---

## Task 13 : Application — ListRequests use case

**Files:**
- Create: `src/webhook_inspector/application/use_cases/list_requests.py`
- Test: `tests/unit/application/test_list_requests.py`

- [ ] **Step 13.1: Write failing test**

Create `tests/unit/application/test_list_requests.py`:

```python
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
    def __init__(self, ep=None): self.ep = ep
    async def save(self, e): ...
    async def find_by_token(self, t): return self.ep if self.ep and self.ep.token == t else None
    async def find_by_id(self, i): return self.ep
    async def increment_request_count(self, i): ...
    async def delete_expired(self) -> int: return 0


class FakeRequestRepo(RequestRepository):
    def __init__(self, items): self.items = items
    async def save(self, r): ...
    async def find_by_id(self, i): return next((r for r in self.items if r.id == i), None)
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
    r1 = CapturedRequest.create(endpoint_id=ep.id, method="GET", path="/h/abc",
        query_string=None, headers={}, body=b"", source_ip="192.0.2.1", inline_threshold_bytes=8192)
    r2 = CapturedRequest.create(endpoint_id=ep.id, method="POST", path="/h/abc",
        query_string=None, headers={}, body=b"", source_ip="192.0.2.1", inline_threshold_bytes=8192)

    uc = ListRequests(FakeEndpointRepo(ep), FakeRequestRepo([r1, r2]))
    result = await uc.execute(token="abc", limit=50)
    assert {r.id for r in result} == {r1.id, r2.id}


async def test_list_unknown_token_raises():
    uc = ListRequests(FakeEndpointRepo(None), FakeRequestRepo([]))
    with pytest.raises(EndpointNotFoundError):
        await uc.execute(token="missing", limit=50)
```

- [ ] **Step 13.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/application/test_list_requests.py -v
```

Expected: import error.

- [ ] **Step 13.3: Implement ListRequests**

Create `src/webhook_inspector/application/use_cases/list_requests.py`:

```python
from dataclasses import dataclass
from uuid import UUID

from webhook_inspector.domain.entities.captured_request import CapturedRequest
from webhook_inspector.domain.ports.endpoint_repository import EndpointRepository
from webhook_inspector.domain.ports.request_repository import RequestRepository


class EndpointNotFoundError(Exception):
    pass


@dataclass
class ListRequests:
    endpoint_repo: EndpointRepository
    request_repo: RequestRepository

    async def execute(
        self,
        token: str,
        limit: int = 50,
        before_id: UUID | None = None,
    ) -> list[CapturedRequest]:
        endpoint = await self.endpoint_repo.find_by_token(token)
        if endpoint is None:
            raise EndpointNotFoundError(token)
        return await self.request_repo.list_by_endpoint(
            endpoint_id=endpoint.id,
            limit=limit,
            before_id=before_id,
        )
```

- [ ] **Step 13.4: Run test, confirm PASS**

```bash
uv run pytest tests/unit/application/test_list_requests.py -v
```

Expected: 2 passed.

- [ ] **Step 13.5: Commit**

```bash
git add src/webhook_inspector/application/use_cases/list_requests.py tests/unit/application/test_list_requests.py
git commit -m "feat(app): add ListRequests use case"
```

---

## Task 14 : Infrastructure — Postgres LISTEN/NOTIFY adapter

**Files:**
- Create: `src/webhook_inspector/infrastructure/notifications/postgres_notifier.py`
- Test: `tests/integration/test_postgres_notifier.py`

LISTEN/NOTIFY is asynchronous and out-of-process. We use a separate raw `psycopg` async connection (not SQLAlchemy session) because LISTEN must hold the connection open.

- [ ] **Step 14.1: Write failing integration test**

Create `tests/integration/test_postgres_notifier.py`:

```python
import asyncio
from uuid import uuid4

import pytest

from webhook_inspector.infrastructure.notifications.postgres_notifier import (
    PostgresNotifier,
)


async def test_publish_then_subscribe_receives_message(database_url):
    notifier = PostgresNotifier(dsn=_to_sync_dsn(database_url))
    await notifier.start()

    endpoint_id = uuid4()
    received: list = []

    async def consume():
        async for req_id in notifier.subscribe(endpoint_id):
            received.append(req_id)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)  # ensure LISTEN active

    expected_request = uuid4()
    await notifier.publish_new_request(endpoint_id, expected_request)

    await asyncio.wait_for(task, timeout=2.0)
    await notifier.stop()

    assert received == [expected_request]


def _to_sync_dsn(async_url: str) -> str:
    return async_url.replace("+psycopg_async", "").replace("+psycopg", "")
```

- [ ] **Step 14.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/test_postgres_notifier.py -v
```

Expected: import error.

- [ ] **Step 14.3: Implement PostgresNotifier**

Create `src/webhook_inspector/infrastructure/notifications/postgres_notifier.py`:

```python
import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
from psycopg import AsyncConnection

from webhook_inspector.domain.ports.notifier import Notifier

logger = logging.getLogger(__name__)


class PostgresNotifier(Notifier):
    """LISTEN/NOTIFY based notifier.

    Channel: ``new_request``
    Payload: ``"<endpoint_id>:<request_id>"``
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._listen_conn: AsyncConnection | None = None
        self._queues: dict[UUID, set[asyncio.Queue[UUID]]] = defaultdict(set)
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._listen_conn is not None:
                return
            self._listen_conn = await psycopg.AsyncConnection.connect(
                self._dsn, autocommit=True
            )
            async with self._listen_conn.cursor() as cur:
                await cur.execute("LISTEN new_request;")
            self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        async with self._lock:
            if self._reader_task is not None:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass
                self._reader_task = None
            if self._listen_conn is not None:
                await self._listen_conn.close()
                self._listen_conn = None

    async def publish_new_request(self, endpoint_id: UUID, request_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn, autocommit=True) as conn:
            payload = f"{endpoint_id}:{request_id}"
            async with conn.cursor() as cur:
                await cur.execute("SELECT pg_notify('new_request', %s);", (payload,))

    async def subscribe(self, endpoint_id: UUID) -> AsyncIterator[UUID]:
        if self._listen_conn is None:
            await self.start()

        queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._queues[endpoint_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[endpoint_id].discard(queue)
            if not self._queues[endpoint_id]:
                del self._queues[endpoint_id]

    async def _read_loop(self) -> None:
        assert self._listen_conn is not None
        try:
            async for notif in self._listen_conn.notifies():
                try:
                    endpoint_str, request_str = notif.payload.split(":", 1)
                    endpoint_id = UUID(endpoint_str)
                    request_id = UUID(request_str)
                except ValueError:
                    logger.warning("malformed_notify_payload", extra={"payload": notif.payload})
                    continue
                for queue in list(self._queues.get(endpoint_id, ())):
                    queue.put_nowait(request_id)
        except Exception:
            logger.exception("notify_reader_crashed")
            raise
```

- [ ] **Step 14.4: Run test, confirm PASS**

```bash
uv run pytest tests/integration/test_postgres_notifier.py -v
```

Expected: 1 passed (allow up to 3s).

- [ ] **Step 14.5: Commit**

```bash
git add src/webhook_inspector/infrastructure/notifications/ tests/integration/test_postgres_notifier.py
git commit -m "feat(infra): add Postgres LISTEN/NOTIFY adapter"
```

---

## Task 15 : Web — App service: POST /api/endpoints

**Files:**
- Create: `src/webhook_inspector/web/app/main.py`, `routes.py`, `deps.py`
- Test: `tests/integration/web/test_app_create_endpoint.py`

- [ ] **Step 15.1: Create dependency wiring module**

Create `src/webhook_inspector/web/app/deps.py`:

```python
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
def _engine():
    settings = get_settings()
    url = settings.database_url.replace(
        "postgresql+psycopg://", "postgresql+psycopg_async://"
    ) if "+psycopg://" in settings.database_url else settings.database_url
    return create_async_engine(url, pool_pre_ping=True, future=True)


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
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CreateEndpoint:
    return CreateEndpoint(
        repo=PostgresEndpointRepository(session),
        ttl_days=settings.endpoint_ttl_days,
    )


async def get_list_requests(
    session: AsyncSession = Depends(get_session),
) -> ListRequests:
    return ListRequests(
        endpoint_repo=PostgresEndpointRepository(session),
        request_repo=PostgresRequestRepository(session),
    )
```

- [ ] **Step 15.2: Write failing test**

Create `tests/integration/web/test_app_create_endpoint.py`:

```python
import httpx
import pytest
from httpx import ASGITransport

from webhook_inspector.web.app.main import app


async def test_post_endpoints_returns_url_and_expiry(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    # Reset deps cache
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/endpoints")
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"].startswith("http")
        assert "/h/" in data["url"]
        assert "expires_at" in data
```

- [ ] **Step 15.3: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_app_create_endpoint.py -v
```

Expected: import error.

- [ ] **Step 15.4: Implement app routes**

Create `src/webhook_inspector/web/app/routes.py`:

```python
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from webhook_inspector.application.use_cases.create_endpoint import CreateEndpoint
from webhook_inspector.web.app.deps import get_create_endpoint

router = APIRouter()


def hook_base_url(request: Request) -> str:
    """Derive the ingestor base URL from the app base URL.

    Prod: app.<domain>  →  hook.<domain>
    Local docker-compose: localhost:8000 → localhost:8001
    """
    base = str(request.base_url).rstrip("/")
    if "://app." in base:
        return base.replace("://app.", "://hook.")
    if ":8000" in base:
        return base.replace(":8000", ":8001")
    return base  # fallback (single-host dev)


class CreateEndpointResponse(BaseModel):
    url: str
    expires_at: str
    token: str


@router.post("/api/endpoints", status_code=201, response_model=CreateEndpointResponse)
async def create_endpoint(
    request: Request,
    use_case: CreateEndpoint = Depends(get_create_endpoint),
) -> CreateEndpointResponse:
    endpoint = await use_case.execute()
    return CreateEndpointResponse(
        url=f"{hook_base_url(request)}/h/{endpoint.token}",
        expires_at=endpoint.expires_at.isoformat(),
        token=endpoint.token,
    )
```

Create `src/webhook_inspector/web/app/main.py`:

```python
from fastapi import FastAPI

from webhook_inspector.web.app.routes import router

app = FastAPI(title="Webhook Inspector — App")
app.include_router(router)
```

- [ ] **Step 15.5: Run test, confirm PASS**

```bash
uv run pytest tests/integration/web/test_app_create_endpoint.py -v
```

Expected: 1 passed.

- [ ] **Step 15.6: Commit**

```bash
git add src/webhook_inspector/web/app/ tests/integration/web/test_app_create_endpoint.py
git commit -m "feat(web): add POST /api/endpoints"
```

---

## Task 16 : Web — Ingestor service: ANY /h/{token}

**Files:**
- Create: `src/webhook_inspector/web/ingestor/main.py`, `routes.py`
- Test: `tests/integration/web/test_ingestor_capture.py`

- [ ] **Step 16.1: Write failing test**

Create `tests/integration/web/test_ingestor_capture.py`:

```python
import httpx
import pytest
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_capture_returns_200_and_persists(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    # reset caches
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    app_deps.get_settings.cache_clear()
    app_deps._engine.cache_clear()
    app_deps._session_factory.cache_clear()
    ing_deps.get_settings.cache_clear()
    ing_deps._engine.cache_clear()
    ing_deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.post("/api/endpoints")
        token = resp.json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post(f"/h/{token}", json={"hello": "world"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get(f"/api/endpoints/{token}/requests")
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["method"] == "POST"


async def test_capture_unknown_token_404(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.ingestor import deps as ing_deps
    ing_deps.get_settings.cache_clear()
    ing_deps._engine.cache_clear()
    ing_deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post("/h/totallymade-up", json={})
        assert resp.status_code == 404


async def test_capture_rejects_oversized_body(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("MAX_BODY_BYTES", "1024")
    from webhook_inspector.web.app import deps as app_deps
    from webhook_inspector.web.ingestor import deps as ing_deps
    for m in (app_deps, ing_deps):
        m.get_settings.cache_clear()
        m._engine.cache_clear()
        m._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.post("/api/endpoints")
        token = resp.json()["token"]

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        resp = await c.post(f"/h/{token}", content=b"x" * 2048)
        assert resp.status_code == 413
```

- [ ] **Step 16.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_ingestor_capture.py -v
```

Expected: import error.

- [ ] **Step 16.3: Create ingestor deps**

Create `src/webhook_inspector/web/ingestor/__init__.py` then `src/webhook_inspector/web/ingestor/deps.py`:

```python
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
    url = settings.database_url.replace(
        "postgresql+psycopg://", "postgresql+psycopg_async://"
    ) if "+psycopg://" in settings.database_url else settings.database_url
    return create_async_engine(url, pool_pre_ping=True, future=True)


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
```

- [ ] **Step 16.4: Create ingestor routes**

Create `src/webhook_inspector/web/ingestor/routes.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request

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
    use_case: CaptureRequest = Depends(get_capture_request),
    settings: Settings = Depends(get_settings),
):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_body_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    try:
        await use_case.execute(
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

    return {"ok": True}
```

Create `src/webhook_inspector/web/ingestor/main.py`:

```python
from fastapi import FastAPI

from webhook_inspector.web.ingestor.routes import router

app = FastAPI(title="Webhook Inspector — Ingestor")
app.include_router(router)
```

- [ ] **Step 16.5: Run test, confirm PASS**

```bash
uv run pytest tests/integration/web/test_ingestor_capture.py -v
```

Expected: 1 fails (the GET endpoint doesn't exist yet — we add it in Task 17). Other 2 pass.

If `test_capture_returns_200_and_persists` fails on the GET part, add a skip marker temporarily:

```python
@pytest.mark.skip(reason="GET /api/endpoints/{token}/requests added in Task 17")
async def test_capture_returns_200_and_persists(...):
```

- [ ] **Step 16.6: Commit**

```bash
git add src/webhook_inspector/web/ingestor/ tests/integration/web/test_ingestor_capture.py
git commit -m "feat(web): add ingestor ANY /h/{token} with size limits"
```

---

## Task 17 : Web — App service: GET /api/endpoints/{token}/requests

**Files:**
- Modify: `src/webhook_inspector/web/app/routes.py`
- Test: `tests/integration/web/test_app_list_requests.py`

- [ ] **Step 17.1: Write failing test**

Create `tests/integration/web/test_app_list_requests.py`:

```python
import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_list_returns_empty_for_new_endpoint(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]
        resp = await c.get(f"/api/endpoints/{token}/requests")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_before_id": None}


async def test_list_unknown_token_returns_404(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get("/api/endpoints/missing/requests")
        assert resp.status_code == 404
```

- [ ] **Step 17.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_app_list_requests.py -v
```

Expected: 404 on the GET path = route not yet defined.

- [ ] **Step 17.3: Add route to app**

Edit `src/webhook_inspector/web/app/routes.py`. **Merge new imports at the top of the file** (alongside existing imports), then **append the new code at the bottom**:

```python
# === merge at top, with existing imports ===
from uuid import UUID

from fastapi import HTTPException

from webhook_inspector.application.use_cases.list_requests import (
    EndpointNotFoundError,
    ListRequests,
)
from webhook_inspector.web.app.deps import get_list_requests
```

Then append at the bottom of the file:

```python
class RequestItem(BaseModel):
    id: UUID
    method: str
    path: str
    body_size: int
    received_at: str


class RequestList(BaseModel):
    items: list[RequestItem]
    next_before_id: UUID | None


@router.get("/api/endpoints/{token}/requests", response_model=RequestList)
async def list_requests(
    token: str,
    limit: int = 50,
    before_id: UUID | None = None,
    use_case: ListRequests = Depends(get_list_requests),
) -> RequestList:
    try:
        items = await use_case.execute(token=token, limit=limit, before_id=before_id)
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    return RequestList(
        items=[
            RequestItem(
                id=r.id,
                method=r.method,
                path=r.path,
                body_size=r.body_size,
                received_at=r.received_at.isoformat(),
            )
            for r in items
        ],
        next_before_id=items[-1].id if len(items) == limit else None,
    )
```

- [ ] **Step 17.4: Run test, confirm PASS**

```bash
uv run pytest tests/integration/web/test_app_list_requests.py -v
uv run pytest tests/integration/web/test_ingestor_capture.py -v  # remove skip from task 16 now
```

Remove the `@pytest.mark.skip` from Task 16's test. All 3 ingestor tests + 2 list tests pass.

- [ ] **Step 17.5: Commit**

```bash
git add src/webhook_inspector/web/app/routes.py tests/integration/web/
git commit -m "feat(web): add GET /api/endpoints/{token}/requests"
```

---

## Task 18 : Web — App service: GET /stream/{token} SSE

**Files:**
- Create: `src/webhook_inspector/web/app/sse.py`
- Modify: `src/webhook_inspector/web/app/routes.py`
- Test: `tests/integration/web/test_sse_stream.py`

- [ ] **Step 18.1: Write failing test**

Create `tests/integration/web/test_sse_stream.py`:

```python
import asyncio

import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service
from webhook_inspector.web.ingestor.main import app as ingestor_service


async def test_sse_delivers_new_request_event(monkeypatch, database_url, tmp_path):
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

    # Open SSE stream
    received: list[str] = []

    async def consume_stream():
        async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
            async with c.stream("GET", f"/stream/{token}", timeout=5.0) as resp:
                async for chunk in resp.aiter_text():
                    received.append(chunk)
                    if "POST" in chunk:
                        return

    consumer = asyncio.create_task(consume_stream())
    await asyncio.sleep(0.3)  # give consumer time to LISTEN

    async with httpx.AsyncClient(transport=ASGITransport(app=ingestor_service), base_url="http://hook") as c:
        await c.post(f"/h/{token}", content=b"hello")

    await asyncio.wait_for(consumer, timeout=5.0)
    full = "".join(received)
    assert "data:" in full
    assert "POST" in full
```

- [ ] **Step 18.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_sse_stream.py -v
```

Expected: 404 route missing.

- [ ] **Step 18.3: Implement SSE handler**

Create `src/webhook_inspector/web/app/sse.py`:

```python
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker

from webhook_inspector.application.use_cases.list_requests import EndpointNotFoundError
from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)
from webhook_inspector.infrastructure.repositories.request_repository import (
    PostgresRequestRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401


async def stream_for_token(
    token: str,
    session_factory: async_sessionmaker,
    notifier: PostgresNotifier,
) -> AsyncIterator[str]:
    # Resolve endpoint
    async with session_factory() as session:
        endpoint = await PostgresEndpointRepository(session).find_by_token(token)
    if endpoint is None:
        raise EndpointNotFoundError(token)

    # Heartbeat + initial connect comment
    yield ": connected\n\n"

    async for request_id in notifier.subscribe(endpoint.id):
        async with session_factory() as session:
            req = await PostgresRequestRepository(session).find_by_id(request_id)
        if req is None:
            continue
        payload = {
            "id": str(req.id),
            "method": req.method,
            "path": req.path,
            "received_at": req.received_at.isoformat(),
            "body_size": req.body_size,
        }
        yield f"event: message\ndata: {json.dumps(payload)}\n\n"
```

Edit `src/webhook_inspector/web/app/routes.py`. **Merge new imports at the top of the file** (alongside existing imports), then **append the new code at the bottom**:

```python
# === merge at top, with existing imports ===
from fastapi.responses import StreamingResponse

from webhook_inspector.infrastructure.notifications.postgres_notifier import PostgresNotifier
from webhook_inspector.web.app.deps import _session_factory, get_notifier
from webhook_inspector.web.app.sse import stream_for_token
```

Then append at the bottom of the file:

```python
@router.get("/stream/{token}")
async def sse_stream(
    token: str,
    notifier: PostgresNotifier = Depends(get_notifier),
):
    try:
        gen = stream_for_token(token, _session_factory(), notifier)
        # Probe to surface 404 before opening stream
        first = await gen.__anext__()
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    async def merged():
        yield first
        async for chunk in gen:
            yield chunk

    return StreamingResponse(
        merged(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 18.4: Run test, confirm PASS**

```bash
uv run pytest tests/integration/web/test_sse_stream.py -v
```

Expected: 1 passed.

- [ ] **Step 18.5: Commit**

```bash
git add src/webhook_inspector/web/app/sse.py src/webhook_inspector/web/app/routes.py tests/integration/web/test_sse_stream.py
git commit -m "feat(web): add SSE /stream/{token} with Postgres LISTEN backend"
```

---

## Task 19 : Web — App service: GET /{token} Jinja2 viewer + HTMX

**Files:**
- Create: `src/webhook_inspector/web/app/templates/viewer.html`, `request_fragment.html`
- Modify: `src/webhook_inspector/web/app/routes.py`, `main.py`
- Test: `tests/integration/web/test_viewer_render.py`

- [ ] **Step 19.1: Write failing test**

Create `tests/integration/web/test_viewer_render.py`:

```python
import httpx
from httpx import ASGITransport

from webhook_inspector.web.app.main import app as app_service


async def test_viewer_renders_with_token(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        token = (await c.post("/api/endpoints")).json()["token"]
        resp = await c.get(f"/{token}")
        assert resp.status_code == 200
        body = resp.text
        assert token in body
        assert "htmx" in body.lower()
        assert "sse-connect" in body


async def test_viewer_404_for_unknown_token(monkeypatch, database_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    monkeypatch.setenv("BLOB_STORAGE_PATH", str(tmp_path))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app_service), base_url="http://test") as c:
        resp = await c.get("/totally-unknown-token-here")
        assert resp.status_code == 404
```

- [ ] **Step 19.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/web/test_viewer_render.py -v
```

Expected: 404 (route missing).

- [ ] **Step 19.3: Create templates**

Create `src/webhook_inspector/web/app/templates/viewer.html`:

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Webhook Inspector — {{ token }}</title>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <script src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen">
  <header class="border-b border-slate-700 px-6 py-4">
    <h1 class="text-xl font-mono">webhook-inspector</h1>
    <p class="text-sm text-slate-400 mt-1">
      URL d'ingestion :
      <code class="bg-slate-800 px-2 py-1 rounded">{{ hook_url }}</code>
    </p>
  </header>

  <main class="px-6 py-4">
    <div hx-ext="sse" sse-connect="/stream/{{ token }}" class="space-y-2">
      <ul id="requests" sse-swap="message" hx-swap="afterbegin" class="space-y-2">
        {% for req in initial_requests %}
          {% include "request_fragment.html" %}
        {% endfor %}
      </ul>
    </div>
  </main>
</body>
</html>
```

Create `src/webhook_inspector/web/app/templates/request_fragment.html`:

```html
<li class="border border-slate-700 rounded px-4 py-2 font-mono text-sm">
  <span class="inline-block w-16 font-bold text-emerald-400">{{ req.method }}</span>
  <span class="text-slate-300">{{ req.path }}</span>
  <span class="text-slate-500 text-xs ml-2">{{ req.received_at }}</span>
  <span class="text-slate-500 text-xs ml-2">({{ req.body_size }} bytes)</span>
</li>
```

- [ ] **Step 19.4: Wire Jinja2 + route**

Edit `src/webhook_inspector/web/app/main.py`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from webhook_inspector.web.app.routes import router

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="Webhook Inspector — App")
app.state.templates = templates
app.include_router(router)
```

Edit `src/webhook_inspector/web/app/routes.py`. **Merge `from fastapi.responses import HTMLResponse` at the top** with existing imports. Then append at the bottom:

```python
@router.get("/{token}", response_class=HTMLResponse)
async def viewer(
    token: str,
    request: Request,
    use_case: ListRequests = Depends(get_list_requests),
):
    try:
        initial = await use_case.execute(token=token, limit=50)
    except EndpointNotFoundError as e:
        raise HTTPException(status_code=404, detail="endpoint not found") from e

    templates = request.app.state.templates
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
                }
                for r in initial
            ],
        },
    )
```

Update SSE handler to send HTML fragments instead of JSON (so HTMX `sse-swap` works). Edit `src/webhook_inspector/web/app/sse.py` — change yield format:

```python
import json
from collections.abc import AsyncIterator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
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


async def stream_for_token(
    token: str,
    session_factory: async_sessionmaker,
    notifier: PostgresNotifier,
) -> AsyncIterator[str]:
    async with session_factory() as session:
        endpoint = await PostgresEndpointRepository(session).find_by_token(token)
    if endpoint is None:
        raise EndpointNotFoundError(token)

    yield ": connected\n\n"

    fragment = _env.get_template("request_fragment.html")
    async for request_id in notifier.subscribe(endpoint.id):
        async with session_factory() as session:
            req = await PostgresRequestRepository(session).find_by_id(request_id)
        if req is None:
            continue
        html = fragment.render(req={
            "method": req.method,
            "path": req.path,
            "body_size": req.body_size,
            "received_at": req.received_at.isoformat(),
        })
        # SSE multi-line data: one "data:" per line
        encoded = "\n".join(f"data: {line}" for line in html.splitlines())
        yield f"event: message\n{encoded}\n\n"
```

- [ ] **Step 19.5: Run test, confirm PASS**

```bash
uv run pytest tests/integration/web/test_viewer_render.py -v
uv run pytest tests/integration/web/test_sse_stream.py -v
```

Both pass. (You may need to relax `assert "POST" in full` to `assert "POST" in full or "post" in full` since HTML is uppercase already.)

- [ ] **Step 19.6: Commit**

```bash
git add src/webhook_inspector/web/app/ tests/integration/web/test_viewer_render.py
git commit -m "feat(web): add Jinja2 viewer template with HTMX + Tailwind via CDN"
```

---

## Task 20 : Jobs — Cleaner cron job

**Files:**
- Create: `src/webhook_inspector/jobs/cleaner.py`
- Test: `tests/integration/test_cleaner.py`

- [ ] **Step 20.1: Write failing integration test**

Create `tests/integration/test_cleaner.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
            id=uuid4(), token="stale-cleanup",
            created_at=datetime.now(UTC) - timedelta(days=10),
            expires_at=datetime.now(UTC) - timedelta(days=3),
            request_count=0,
        )
        await repo.save(fresh)
        await repo.save(stale)
        await s.commit()

    sync_dsn = database_url.replace("+psycopg_async", "+psycopg")
    deleted = await run_cleanup(database_url=sync_dsn)
    assert deleted >= 1

    async with session_factory() as s:
        repo = PostgresEndpointRepository(s)
        assert await repo.find_by_token("fresh-cleanup") is not None
        assert await repo.find_by_token("stale-cleanup") is None
```

- [ ] **Step 20.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/test_cleaner.py -v
```

Expected: import error.

- [ ] **Step 20.3: Implement cleaner**

Create `src/webhook_inspector/jobs/cleaner.py`:

```python
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.repositories.endpoint_repository import (
    PostgresEndpointRepository,
)

logger = logging.getLogger(__name__)


async def run_cleanup(database_url: str) -> int:
    url = database_url.replace(
        "postgresql+psycopg://", "postgresql+psycopg_async://"
    ) if "+psycopg://" in database_url else database_url
    engine = create_async_engine(url, future=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )
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
    deleted = asyncio.run(run_cleanup(settings.database_url))
    sys.stdout.write(f"deleted {deleted} expired endpoints\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 20.4: Run test, confirm PASS**

```bash
uv run pytest tests/integration/test_cleaner.py -v
```

Expected: 1 passed.

- [ ] **Step 20.5: Commit**

```bash
git add src/webhook_inspector/jobs/ tests/integration/test_cleaner.py
git commit -m "feat(jobs): add cleaner that deletes expired endpoints"
```

---

## Task 21 : Observability — structlog + OpenTelemetry auto-instrumentation

**Files:**
- Create: `src/webhook_inspector/observability/logging.py`, `tracing.py`
- Modify: `src/webhook_inspector/web/app/main.py`, `web/ingestor/main.py`, `jobs/cleaner.py`
- Test: `tests/unit/observability/test_logging.py`

- [ ] **Step 21.1: Write a smoke test for structlog config**

Create `tests/unit/observability/test_logging.py`:

```python
import json
import logging
from io import StringIO

from webhook_inspector.observability.logging import configure_logging


def test_configure_logging_emits_json(capsys):
    configure_logging(level="INFO", service_name="test-svc")
    logger = logging.getLogger("test_logger")
    logger.info("hello world", extra={"user_id": 42})

    captured = capsys.readouterr().out
    line = captured.strip().split("\n")[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello world"
    assert payload["service.name"] == "test-svc"
    assert payload["user_id"] == 42
```

- [ ] **Step 21.2: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/observability/test_logging.py -v
```

Expected: import error.

- [ ] **Step 21.3: Implement structlog config**

Create `src/webhook_inspector/observability/__init__.py` (empty).

Create `src/webhook_inspector/observability/logging.py`:

```python
import logging
import sys

import structlog


def configure_logging(level: str, service_name: str) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_ServiceNameFilter(service_name))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


class _ServiceNameFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.__dict__["service.name"] = self._service_name
        return True
```

- [ ] **Step 21.4: Implement tracing setup**

Create `src/webhook_inspector/observability/tracing.py`:

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def configure_tracing(service_name: str, environment: str, otlp_endpoint: str | None = None) -> None:
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": environment,
    })
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def instrument_app(app, engine=None) -> None:
    FastAPIInstrumentor.instrument_app(app)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
```

- [ ] **Step 21.5: Wire into services**

Edit `src/webhook_inspector/web/app/main.py` to call setup:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.app.deps import _engine
from webhook_inspector.web.app.routes import router

_settings = Settings()
configure_logging(_settings.log_level, _settings.service_name + "-app")
configure_tracing(_settings.service_name + "-app", _settings.environment, None)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="Webhook Inspector — App")
app.state.templates = templates
app.include_router(router)
instrument_app(app, _engine())
```

Equivalent edits to `src/webhook_inspector/web/ingestor/main.py`:

```python
from fastapi import FastAPI

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.ingestor.deps import _engine
from webhook_inspector.web.ingestor.routes import router

_settings = Settings()
configure_logging(_settings.log_level, _settings.service_name + "-ingestor")
configure_tracing(_settings.service_name + "-ingestor", _settings.environment, None)

app = FastAPI(title="Webhook Inspector — Ingestor")
app.include_router(router)
instrument_app(app, _engine())
```

Edit `src/webhook_inspector/jobs/cleaner.py` — at top of `main()` add:

```python
def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-cleaner")
    configure_tracing(settings.service_name + "-cleaner", settings.environment, None)
    deleted = asyncio.run(run_cleanup(settings.database_url))
    sys.stdout.write(f"deleted {deleted} expired endpoints\n")
```

(Add the `from webhook_inspector.observability.*` imports at the top of `cleaner.py`.)

- [ ] **Step 21.6: Run test, confirm PASS**

```bash
uv run pytest tests/unit/observability/ -v
uv run pytest tests/ -v   # full suite — ensure nothing regressed
```

Expected: all green.

- [ ] **Step 21.7: Commit**

```bash
git add src/webhook_inspector/observability/ src/webhook_inspector/web/ src/webhook_inspector/jobs/ tests/unit/observability/
git commit -m "feat(obs): add structlog JSON logs and OpenTelemetry tracing (console exporter)"
```

---

## Task 22 : Docker — multi-stage image + final docker-compose

**Files:**
- Create: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 22.1: Write Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
RUN pip install uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app
COPY migrations ./migrations
COPY alembic.ini ./

EXPOSE 8000 8001
CMD ["uvicorn", "webhook_inspector.web.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 22.2: Rewrite docker-compose.yml**

Replace `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: webhook
      POSTGRES_PASSWORD: webhook
      POSTGRES_DB: webhook_inspector
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U webhook"]
      interval: 5s
      timeout: 5s
      retries: 5

  migrate:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg://webhook:webhook@postgres:5432/webhook_inspector
    command: ["alembic", "upgrade", "head"]
    restart: "no"

  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    environment:
      DATABASE_URL: postgresql+psycopg://webhook:webhook@postgres:5432/webhook_inspector
      BLOB_STORAGE_PATH: /data/blobs
      LOG_LEVEL: INFO
      ENVIRONMENT: local
    ports:
      - "8000:8000"
    volumes:
      - blob_data:/data/blobs
    command: ["uvicorn", "webhook_inspector.web.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

  ingestor:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    environment:
      DATABASE_URL: postgresql+psycopg://webhook:webhook@postgres:5432/webhook_inspector
      BLOB_STORAGE_PATH: /data/blobs
      LOG_LEVEL: INFO
      ENVIRONMENT: local
    ports:
      - "8001:8001"
    volumes:
      - blob_data:/data/blobs
    command: ["uvicorn", "webhook_inspector.web.ingestor.main:app", "--host", "0.0.0.0", "--port", "8001"]

volumes:
  postgres_data:
  blob_data:
```

- [ ] **Step 22.3: Build and run**

```bash
docker compose down -v
docker compose up -d --build
```

Wait ~10s for migrate to complete, then:

```bash
docker compose ps
curl -sX POST http://localhost:8000/api/endpoints | python -m json.tool
```

Expected: JSON with `url` containing `http://localhost:8001/h/<token>` (the `hook_base_url` helper introduced in Task 15 handles the `:8000` → `:8001` swap automatically for docker-compose dev).

- [ ] **Step 22.4: Smoke test full stack manually**

```bash
TOKEN=$(curl -sX POST http://localhost:8000/api/endpoints | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo "token: $TOKEN"
curl -sX POST -d '{"hello":"world"}' http://localhost:8001/h/$TOKEN
curl -s http://localhost:8000/api/endpoints/$TOKEN/requests | python -m json.tool
open http://localhost:8000/$TOKEN  # or visit manually
```

Expected: viewer page shows 1 request. Send another curl to see it appear live (no refresh).

- [ ] **Step 22.5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore(docker): multi-stage Dockerfile and full docker-compose stack"
```

---

## Task 23 : E2E smoke test

**Files:**
- Create: `tests/e2e/test_smoke.py`
- Create: `scripts/wait-for-stack.sh`

- [ ] **Step 23.1: Write smoke test (requires running stack)**

Create `tests/e2e/test_smoke.py`:

```python
import asyncio
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("E2E_BASE_URL"),
    reason="E2E_BASE_URL not set — start docker-compose and export E2E_BASE_URL=http://localhost",
)


@pytest.fixture
def base_app_url() -> str:
    return os.environ["E2E_BASE_URL"] + ":8000"


@pytest.fixture
def base_hook_url() -> str:
    return os.environ["E2E_BASE_URL"] + ":8001"


async def test_smoke_full_flow(base_app_url, base_hook_url):
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{base_app_url}/api/endpoints")
        assert resp.status_code == 201
        token = resp.json()["token"]

        for i in range(3):
            r = await c.post(f"{base_hook_url}/h/{token}", json={"i": i})
            assert r.status_code == 200

        listing = await c.get(f"{base_app_url}/api/endpoints/{token}/requests")
        assert listing.status_code == 200
        assert len(listing.json()["items"]) == 3
```

Create `scripts/wait-for-stack.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "waiting for app on :8000..."
for _ in $(seq 1 30); do
  if curl -fs http://localhost:8000/api/endpoints -X POST -o /dev/null; then
    echo "app ready"
    break
  fi
  sleep 1
done
```

```bash
chmod +x scripts/wait-for-stack.sh
```

- [ ] **Step 23.2: Run E2E**

```bash
docker compose up -d --build
./scripts/wait-for-stack.sh
E2E_BASE_URL=http://localhost uv run pytest tests/e2e -v
```

Expected: 1 passed.

- [ ] **Step 23.3: Commit**

```bash
git add tests/e2e/ scripts/
git commit -m "test(e2e): add smoke test for full local stack"
```

---

## Task 24 : CI — GitHub Actions lint+test workflow

**Files:**
- Create: `.github/workflows/lint-and-test.yml`

- [ ] **Step 24.1: Write workflow**

Create `.github/workflows/lint-and-test.yml`:

```yaml
name: lint-and-test

on:
  pull_request:
  push:
    branches: [main, develop]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.13"
      - run: uv sync --frozen
      - run: uv run ruff check src tests
      - run: uv run ruff format --check src tests

  type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.13"
      - run: uv sync --frozen
      - run: uv run mypy src

  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.13"
      - run: uv sync --frozen
      - run: uv run pytest tests/unit -v

  integration:
    runs-on: ubuntu-latest
    services:
      docker:
        image: docker:dind
        options: --privileged
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.13"
      - run: uv sync --frozen
      - run: uv run pytest tests/integration -v
```

- [ ] **Step 24.2: Commit**

```bash
git add .github/
git commit -m "ci: add lint, type-check, unit and integration test workflow"
```

---

## Task 25 : README + final polish

**Files:**
- Create: `README.md`

- [ ] **Step 25.1: Write README**

Create `README.md`:

```markdown
# Webhook Inspector

A self-hostable webhook inspection service. Generate a URL, point any webhook at it, see requests in real-time in your browser.

This is a learning side-project — see `docs/specs/2026-05-11-webhook-inspector-design.md` for design rationale and roadmap.

## Quick start (local)

Requires Docker + docker-compose.

```bash
make up
# wait ~10s for migrate to complete

# Create an endpoint
TOKEN=$(curl -sX POST http://localhost:8000/api/endpoints | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Send a webhook
curl -X POST -d '{"hello":"world"}' http://localhost:8001/h/$TOKEN

# Watch it live
open http://localhost:8000/$TOKEN
```

## Development

```bash
make install   # uv sync
make lint      # ruff
make type      # mypy
make test      # full pytest suite
make up        # full docker-compose stack
make clean     # run cleaner job manually
```

## Architecture

Two FastAPI services + one job, all sharing the same Python package:

- `app` (port 8000) — UI + API + SSE
- `ingestor` (port 8001) — webhook capture endpoint (public, adversarial traffic)
- `cleaner` — cron job, deletes expired endpoints

See spec at `docs/specs/2026-05-11-webhook-inspector-design.md`.
```

- [ ] **Step 25.2: Run final full test pass**

```bash
make lint
make type
make test-unit
make test-int
```

Expected: all green.

- [ ] **Step 25.3: Commit**

```bash
git add README.md
git commit -m "docs: add README with quickstart and architecture overview"
```

---

## Self-Review

(To run after writing the plan — fix inline.)

**1. Spec coverage** :
- POST /api/endpoints — Task 15 ✓
- ANY /h/{token} — Task 16 ✓
- GET /api/endpoints/{token}/requests — Task 17 ✓
- GET /{token} viewer — Task 19 ✓
- GET /stream/{token} SSE — Task 18 ✓
- Token generation — Task 4 ✓
- Body offload 8KB / max 10MB — Tasks 3, 12, 16 ✓
- Postgres LISTEN/NOTIFY — Task 14 ✓
- Cleaner — Task 20 ✓
- structlog + OTEL — Task 21 ✓
- docker-compose — Task 22 ✓
- CI — Task 24 ✓
- Tests (unit/integration/e2e) — couvert dans toutes les tâches + Task 23 ✓
- **Out of scope Phase A** : GCS, Terraform, Cloudflare, CI/CD prod — sera couvert dans Phases B et C.

**2. Type consistency** :
- `Endpoint` fields cohérents dans tout le plan.
- `CapturedRequest` fields cohérents.
- `EndpointRepository.delete_expired` retourne `int` partout.
- `BlobStorage.put/get` signatures stables.

**3. Pas de placeholders détectés**.

## Next Steps (post-Phase A)

Une fois Phase A livrée et testée localement :

1. **Phase B Plan** : Terraform pour GCP (project, VPC, Cloud SQL, GCS, Cloud Run services + Job, Cloud Scheduler, Secret Manager, IAM, Artifact Registry). Le `LocalBlobStorage` sera remplacé par un `GcsBlobStorage`. Premier deploy manuel.

2. **Phase C Plan** : GitHub Actions deploy workflows avec Workload Identity Federation. Cloudflare DNS + TLS. Export OTEL vers Cloud Trace + Cloud Logging. Premier deploy auto en prod.

Chacun de ces plans démarrera par une re-validation du scope avec le user.
