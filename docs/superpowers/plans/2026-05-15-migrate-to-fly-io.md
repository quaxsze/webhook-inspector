# Migrate to Fly.io (self-managed Postgres, fresh start) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the webhook-inspector deployment from GCP (Cloud Run + Cloud SQL + GCS + Cloud Trace/Monitoring) to Fly.io (Machines + self-managed Postgres + Cloudflare R2 + Honeycomb) with a fresh database (no data migration), preserving the custom domains `app.odessa-inspect.org` (web) and `hook.odessa-inspect.org` (ingestor). Note: `web/app/routes.py:hook_base_url()` rewrites `app.` → `hook.` to derive webhook URLs, so the web service **must** live on `app.<domain>` for the returned URLs to be correct.

**Architecture:**
1. Code changes are **additive** — add OTLP exporter branches alongside the existing Cloud Trace/Monitoring branches, and add an S3-compatible blob storage adapter alongside GCS. These ship to Cloud Run first and are validated in production *before* any Fly traffic, so the cutover is just an env-var flip.
2. Three Fly apps: `webhook-inspector-db` (Postgres on Machine + volume, self-managed via `flyio/postgres-flex`), `webhook-inspector-web` (FastAPI app), `webhook-inspector-ingestor` (FastAPI ingestor). All in `cdg`. Single image strategy preserved: same `Dockerfile`, different `[processes]` or different fly.toml.
3. Blob storage moves to **Cloudflare R2** (S3-compatible, free egress, single-provider story with Cloudflare DNS). Object storage is the only stateful component besides Postgres.
4. Cleaner job runs as a **GitHub Actions cron** that calls `fly machine run --rm` with the latest image — no permanent infra needed.
5. DNS cutover flips the two existing Cloudflare CNAMEs (`app` and `hook`) from `ghs.googlehosted.com` to `<app>.fly.dev`. Apex `odessa-inspect.org` untouched. **No production users at this stage** → we keep Cloud Run warm ~30–60 min post-cutover as a safety net (not 48h), then proceed to teardown.

**Threat model note**: this is a personal side-project with no current users. Phase A's code changes are still written as backward-compatible (additive branches) because the cost is near-zero and it makes the cutover trivially safe, but we deliberately skip the "deploy to Cloud Run and validate Cloud Trace first" gate — there's no production traffic worth protecting. The branch `feat/migrate-to-fly` stays open through Phases B–D and merges only after Fly is fully validated end-to-end.

**Tech Stack:** Fly.io Machines (`shared-cpu-1x` 512MB), `flyio/postgres-flex:16` (self-managed PG), Cloudflare R2 (S3-compatible storage), OpenTelemetry OTLP exporter → Honeycomb, Cloudflare DNS-only, GitHub Actions + `flyctl`.

**Pre-requisites:**
- Fly.io account created, `flyctl` installed (`brew install flyctl`), `fly auth login` done.
- Honeycomb free-tier account, API key generated (will be passed via `OTLP_HEADERS=x-honeycomb-team=…`).
- Cloudflare R2 enabled on the existing Cloudflare account, an API token with R2 read/write created.
- Branch: `feat/migrate-to-fly` cut from `main`.

**Naming conventions used in this plan** (pick once, used everywhere):
- Settings field: `otlp_endpoint` → env var `OTLP_ENDPOINT`. Headers: `OTLP_HEADERS` (comma-separated `key=value` pairs). No use of `OTEL_EXPORTER_OTLP_*` — pydantic-settings derives env names from attribute names by default.
- DB instance name in GCP: `webhook-inspector-pg-dev` (from `locals.tf:11`: `${name_prefix}-pg-${environment}`).
- Fly app names: `webhook-inspector-web`, `webhook-inspector-ingestor`, `webhook-inspector-db`.
- Custom domains: `app.odessa-inspect.org` → web, `hook.odessa-inspect.org` → ingestor.

---

## Phase A — Code changes (ship to Cloud Run first)

These changes are backward-compatible: the existing `CLOUD_TRACE_ENABLED=true` + `BLOB_STORAGE_BACKEND=gcs` configuration keeps working. New `OTLP_ENDPOINT` and `BLOB_STORAGE_BACKEND=s3` branches are added (env-var names per "Naming conventions" above).

### Task A1: Extend `Settings` with OTLP and S3 config

**Files:**
- Modify: `src/webhook_inspector/config.py`
- Test: `tests/unit/test_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config.py`:
```python
from webhook_inspector.config import Settings


def test_settings_defaults_keep_gcs_and_no_otlp():
    s = Settings(database_url="postgresql+psycopg://x@y/z")
    assert s.blob_storage_backend == "local"
    assert s.otlp_endpoint is None
    assert s.s3_bucket_name is None


def test_settings_accepts_s3_backend_and_otlp(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    monkeypatch.setenv("BLOB_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "wi-blobs")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://acc.r2.cloudflarestorage.com")
    monkeypatch.setenv("OTLP_ENDPOINT", "https://api.honeycomb.io")
    s = Settings()
    assert s.blob_storage_backend == "s3"
    assert s.s3_bucket_name == "wi-blobs"
    assert s.s3_endpoint_url == "https://acc.r2.cloudflarestorage.com"
    assert s.otlp_endpoint == "https://api.honeycomb.io"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `pydantic_core.ValidationError` on the `s3` literal value, and `AttributeError` on `otlp_endpoint`.

- [ ] **Step 3: Add the new fields**

Modify `src/webhook_inspector/config.py`:
```python
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    blob_storage_path: str = "./blobs"
    blob_storage_backend: Literal["local", "gcs", "s3"] = "local"
    gcs_bucket_name: str | None = None
    s3_endpoint_url: str | None = None
    s3_bucket_name: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "auto"
    endpoint_ttl_days: int = 7
    max_body_bytes: int = 10 * 1024 * 1024
    body_inline_threshold_bytes: int = 8 * 1024
    export_max_requests: int = 10_000
    environment: str = "local"
    service_name: str = "webhook-inspector"
    log_level: str = "INFO"
    cloud_trace_enabled: bool = False
    cloud_metrics_enabled: bool = False
    otlp_endpoint: str | None = None
    otlp_headers: str | None = None
    trace_sample_ratio: float = 0.1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS, both tests green.

- [ ] **Step 5: Lint + type check**

Run: `uv run ruff check src/webhook_inspector/config.py tests/unit/test_config.py && uv run mypy src/webhook_inspector/config.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/webhook_inspector/config.py tests/unit/test_config.py
git commit -m "feat(config): add OTLP and S3 settings (backward-compatible)"
```

---

### Task A2: Add OTLP branch to `configure_tracing`

**Files:**
- Modify: `src/webhook_inspector/observability/tracing.py`
- Test: `tests/unit/observability/test_tracing.py` (create)

**Design note:** `opentelemetry.trace.set_tracer_provider()` is a global singleton — calling it twice in a test process raises "Overriding ... is not allowed" and silently keeps the first provider. To test both branches in the same process, we **extract a pure builder** `_build_tracer_provider()` that returns a `TracerProvider` *without* setting it globally. `configure_tracing()` calls the builder and then sets the global. Tests assert on the builder return value; the global side-effect is covered end-to-end in B3 step 7.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/observability/test_tracing.py`:
```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

from webhook_inspector.observability.tracing import _build_tracer_provider


def _exporter_class_names(provider: TracerProvider) -> list[str]:
    """Walk the active span processor and return the exporter class names."""
    multi = provider._active_span_processor  # type: ignore[attr-defined]
    processors = getattr(multi, "_span_processors", [multi])
    out: list[str] = []
    for proc in processors:
        if isinstance(proc, (BatchSpanProcessor, SimpleSpanProcessor)):
            exporter = getattr(proc, "span_exporter", None) or getattr(
                proc, "_exporter", None
            )
            if exporter is not None:
                out.append(type(exporter).__name__)
    return out


def test_otlp_endpoint_builds_otlp_exporter():
    provider = _build_tracer_provider(
        service_name="test-svc",
        environment="test",
        otlp_endpoint="https://api.honeycomb.io",
        otlp_headers="x-honeycomb-team=abc",
    )
    assert isinstance(provider, TracerProvider)
    names = _exporter_class_names(provider)
    assert any("OTLPSpanExporter" in n for n in names), names


def test_no_otlp_no_cloud_trace_falls_back_to_console():
    provider = _build_tracer_provider(
        service_name="test-svc",
        environment="test",
        otlp_endpoint=None,
        cloud_trace_enabled=False,
    )
    assert isinstance(provider, TracerProvider)
    names = _exporter_class_names(provider)
    assert any("ConsoleSpanExporter" in n for n in names), names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/observability/test_tracing.py -v`
Expected: FAIL — `_build_tracer_provider` doesn't exist yet.

- [ ] **Step 3: Add the OTLP branch + extract the pure builder**

Replace `src/webhook_inspector/observability/tracing.py` with:
```python
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from sqlalchemy.ext.asyncio import AsyncEngine


def _build_tracer_provider(
    service_name: str,
    environment: str,
    cloud_trace_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    sample_ratio: float = 0.1,
) -> TracerProvider:
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(sample_ratio))

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=f"{otlp_endpoint}/v1/traces",
                    headers=_parse_headers(otlp_headers),
                )
            )
        )
    elif cloud_trace_enabled:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))  # type: ignore[no-untyped-call]
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    return provider


def configure_tracing(
    service_name: str,
    environment: str,
    cloud_trace_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    sample_ratio: float = 0.1,
) -> None:
    provider = _build_tracer_provider(
        service_name=service_name,
        environment=environment,
        cloud_trace_enabled=cloud_trace_enabled,
        otlp_endpoint=otlp_endpoint,
        otlp_headers=otlp_headers,
        sample_ratio=sample_ratio,
    )
    trace.set_tracer_provider(provider)


def _parse_headers(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def instrument_app(app: FastAPI, engine: AsyncEngine | None = None) -> None:
    FastAPIInstrumentor.instrument_app(app)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/observability/test_tracing.py -v`
Expected: PASS.

- [ ] **Step 5: Update call sites to pass OTLP settings**

The call sites that build a tracing config are `web/app/main.py` (FastAPI lifespan), `web/ingestor/main.py` (FastAPI lifespan), and `jobs/cleaner.py` + `jobs/migrator.py`. Find them:
```bash
grep -rn "configure_tracing" src/webhook_inspector/
```

For each call site, add `otlp_endpoint=settings.otlp_endpoint, otlp_headers=settings.otlp_headers,` to the call. Example for `jobs/cleaner.py:44`:
```python
configure_tracing(
    settings.service_name + "-cleaner",
    settings.environment,
    cloud_trace_enabled=settings.cloud_trace_enabled,
    otlp_endpoint=settings.otlp_endpoint,
    otlp_headers=settings.otlp_headers,
    sample_ratio=settings.trace_sample_ratio,
)
```

- [ ] **Step 6: Run full test suite to check nothing regressed**

Run: `uv run pytest -x`
Expected: all green (existing tests unaffected since otlp_endpoint defaults to None).

- [ ] **Step 7: Lint + type check**

Run: `uv run ruff check src/ tests/ && uv run mypy src/`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/webhook_inspector/observability/tracing.py \
        tests/unit/observability/test_tracing.py \
        src/webhook_inspector/web/app/main.py \
        src/webhook_inspector/web/ingestor/main.py \
        src/webhook_inspector/jobs/cleaner.py \
        src/webhook_inspector/jobs/migrator.py
git commit -m "feat(observability): add OTLP exporter branch alongside Cloud Trace"
```

---

### Task A3: Add OTLP branch to `configure_metrics`

**Files:**
- Modify: `src/webhook_inspector/observability/metrics.py`
- Test: `tests/unit/observability/test_metrics.py` (create)

**Design note:** same singleton issue as A2. We extract `_build_meter_provider()` returning a `MeterProvider`, tested in isolation; `configure_metrics()` calls it and sets the global.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/observability/test_metrics.py`:
```python
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from webhook_inspector.observability.metrics import _build_meter_provider


def _exporter_class_names(provider: MeterProvider) -> list[str]:
    readers = provider._sdk_config.metric_readers  # type: ignore[attr-defined]
    out: list[str] = []
    for r in readers:
        if isinstance(r, PeriodicExportingMetricReader):
            exporter = getattr(r, "_exporter", None)
            if exporter is not None:
                out.append(type(exporter).__name__)
    return out


def test_otlp_endpoint_builds_otlp_exporter():
    provider = _build_meter_provider(
        service_name="test-svc",
        otlp_endpoint="https://api.honeycomb.io",
        otlp_headers="x-honeycomb-team=abc",
    )
    assert isinstance(provider, MeterProvider)
    names = _exporter_class_names(provider)
    assert any("OTLPMetricExporter" in n for n in names), names


def test_no_otlp_no_cloud_metrics_falls_back_to_console():
    provider = _build_meter_provider(service_name="test-svc")
    assert isinstance(provider, MeterProvider)
    names = _exporter_class_names(provider)
    assert any("ConsoleMetricExporter" in n for n in names), names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/observability/test_metrics.py -v`
Expected: FAIL — `_build_meter_provider` doesn't exist yet.

- [ ] **Step 3: Add the OTLP metrics branch + extract the pure builder**

Replace `src/webhook_inspector/observability/metrics.py` with:
```python
"""Metrics provider configuration. Mirrors the pattern in tracing.py."""

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

_provider: MeterProvider | None = None


def _build_meter_provider(
    service_name: str,
    cloud_metrics_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
) -> MeterProvider:
    resource = Resource.create({"service.name": service_name})

    exporter: MetricExporter
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )

        exporter = OTLPMetricExporter(
            endpoint=f"{otlp_endpoint}/v1/metrics",
            headers=_parse_headers(otlp_headers),
        )
    elif cloud_metrics_enabled:
        from opentelemetry.exporter.cloud_monitoring import (
            CloudMonitoringMetricsExporter,
        )

        exporter = CloudMonitoringMetricsExporter()
    else:
        exporter = ConsoleMetricExporter()

    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    return MeterProvider(resource=resource, metric_readers=[reader])


def configure_metrics(
    service_name: str,
    cloud_metrics_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
) -> None:
    """Configure the global MeterProvider for the running process."""
    global _provider
    _provider = _build_meter_provider(
        service_name=service_name,
        cloud_metrics_enabled=cloud_metrics_enabled,
        otlp_endpoint=otlp_endpoint,
        otlp_headers=otlp_headers,
    )
    metrics.set_meter_provider(_provider)


def _parse_headers(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def force_flush_metrics(timeout_millis: int = 5000) -> None:
    """Flush any pending metric exports. Critical for short-lived jobs."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=timeout_millis)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/observability/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Update `configure_metrics` call sites**

Find them:
```bash
grep -rn "configure_metrics" src/webhook_inspector/
```
For each call, add `otlp_endpoint=settings.otlp_endpoint, otlp_headers=settings.otlp_headers,`. Example for `jobs/cleaner.py:62`:
```python
configure_metrics(
    service_name=settings.service_name + "-cleaner",
    cloud_metrics_enabled=settings.cloud_metrics_enabled,
    otlp_endpoint=settings.otlp_endpoint,
    otlp_headers=settings.otlp_headers,
)
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x`
Expected: all green.

- [ ] **Step 7: Lint + type check**

Run: `uv run ruff check src/ tests/ && uv run mypy src/`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/webhook_inspector/observability/metrics.py \
        tests/unit/observability/test_metrics.py \
        src/webhook_inspector/web/app/main.py \
        src/webhook_inspector/web/ingestor/main.py \
        src/webhook_inspector/jobs/cleaner.py \
        src/webhook_inspector/jobs/migrator.py
git commit -m "feat(observability): add OTLP metrics exporter branch alongside Cloud Monitoring"
```

---

### Task A4: Add `boto3` dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (auto)

- [ ] **Step 1: Add boto3**

Run: `uv add 'boto3>=1.34'`
Expected: `pyproject.toml` updated, `uv.lock` regenerated.

- [ ] **Step 2: Verify install**

Run: `uv run python -c "import boto3; print(boto3.__version__)"`
Expected: version string printed (>=1.34).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add boto3 for S3-compatible blob storage"
```

---

### Task A5: Add `S3BlobStorage` adapter

**Files:**
- Create: `src/webhook_inspector/infrastructure/storage/s3_blob_storage.py`
- Test: `tests/integration/storage/test_s3_blob_storage.py` (create)

- [ ] **Step 1: Write the failing integration test (with MinIO via testcontainers)**

Create `tests/integration/storage/test_s3_blob_storage.py`:
```python
import pytest
from testcontainers.minio import MinioContainer

from webhook_inspector.infrastructure.storage.s3_blob_storage import S3BlobStorage


@pytest.fixture(scope="module")
def minio():
    with MinioContainer() as m:
        client = m.get_client()
        client.make_bucket("test-bucket")
        yield m


@pytest.mark.asyncio
async def test_put_then_get_roundtrips(minio):
    cfg = minio.get_config()
    storage = S3BlobStorage(
        endpoint_url=f"http://{cfg['endpoint']}",
        bucket_name="test-bucket",
        access_key_id=cfg["access_key"],
        secret_access_key=cfg["secret_key"],
        region="us-east-1",
    )
    await storage.put("foo/bar.bin", b"hello world")
    got = await storage.get("foo/bar.bin")
    assert got == b"hello world"


@pytest.mark.asyncio
async def test_get_missing_key_returns_none(minio):
    cfg = minio.get_config()
    storage = S3BlobStorage(
        endpoint_url=f"http://{cfg['endpoint']}",
        bucket_name="test-bucket",
        access_key_id=cfg["access_key"],
        secret_access_key=cfg["secret_key"],
        region="us-east-1",
    )
    got = await storage.get("does/not/exist")
    assert got is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_s3_blob_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: webhook_inspector.infrastructure.storage.s3_blob_storage`.

- [ ] **Step 3: Implement the adapter**

Create `src/webhook_inspector/infrastructure/storage/s3_blob_storage.py`:
```python
"""S3-compatible BlobStorage adapter (works with AWS S3, Cloudflare R2, MinIO, Tigris).

Uses boto3 with asyncio.to_thread to wrap the sync client — same pattern as
GcsBlobStorage. Blob writes are off the hot request path so the thread-pool
hop is acceptable.
"""

import asyncio

import boto3
from botocore.exceptions import ClientError

from webhook_inspector.domain.ports.blob_storage import BlobStorage


class S3BlobStorage(BlobStorage):
    def __init__(
        self,
        endpoint_url: str,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        key_prefix: str = "",
    ) -> None:
        self._bucket_name = bucket_name
        self._key_prefix = key_prefix.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    async def put(self, key: str, data: bytes) -> None:
        full_key = self._full_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket_name,
            Key=full_key,
            Body=data,
        )

    async def get(self, key: str) -> bytes | None:
        full_key = self._full_key(key)
        try:
            obj = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket_name,
                Key=full_key,
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        return bytes(obj["Body"].read())

    def _full_key(self, key: str) -> str:
        if self._key_prefix:
            return f"{self._key_prefix}/{key}"
        return key
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/storage/test_s3_blob_storage.py -v`
Expected: both tests PASS (testcontainers will pull the MinIO image on first run, ~30s).

- [ ] **Step 5: Lint + type check**

Run: `uv run ruff check src/webhook_inspector/infrastructure/storage/ tests/integration/storage/ && uv run mypy src/webhook_inspector/infrastructure/storage/s3_blob_storage.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/webhook_inspector/infrastructure/storage/s3_blob_storage.py \
        tests/integration/storage/test_s3_blob_storage.py
git commit -m "feat(storage): add S3-compatible blob storage adapter"
```

---

### Task A6: Wire S3 backend in the factory

**Files:**
- Modify: `src/webhook_inspector/infrastructure/storage/factory.py`
- Test: `tests/unit/storage/test_factory.py` (create or extend)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/storage/test_factory.py`:
```python
import pytest

from webhook_inspector.config import Settings
from webhook_inspector.infrastructure.storage.factory import make_blob_storage
from webhook_inspector.infrastructure.storage.s3_blob_storage import S3BlobStorage


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://x@y/z",
        **overrides,
    )


def test_factory_returns_s3_when_backend_is_s3():
    s = _settings(
        blob_storage_backend="s3",
        s3_endpoint_url="https://acc.r2.cloudflarestorage.com",
        s3_bucket_name="wi-blobs",
        s3_access_key_id="ak",
        s3_secret_access_key="sk",
    )
    storage = make_blob_storage(s)
    assert isinstance(storage, S3BlobStorage)


def test_factory_raises_when_s3_config_incomplete():
    s = _settings(blob_storage_backend="s3", s3_bucket_name="wi-blobs")
    with pytest.raises(ValueError, match="S3"):
        make_blob_storage(s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/storage/test_factory.py -v`
Expected: FAIL — factory doesn't handle "s3" yet.

- [ ] **Step 3: Add the s3 branch to the factory**

Replace `src/webhook_inspector/infrastructure/storage/factory.py` with:
```python
from webhook_inspector.config import Settings
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


def make_blob_storage(settings: Settings) -> BlobStorage:
    backend = settings.blob_storage_backend.lower()
    if backend == "local":
        return LocalBlobStorage(base_path=settings.blob_storage_path)
    if backend == "gcs":
        if not settings.gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME must be set when BLOB_STORAGE_BACKEND=gcs")
        from webhook_inspector.infrastructure.storage.gcs_blob_storage import (
            GcsBlobStorage,
        )

        return GcsBlobStorage(bucket_name=settings.gcs_bucket_name)
    if backend == "s3":
        missing = [
            n
            for n, v in (
                ("S3_ENDPOINT_URL", settings.s3_endpoint_url),
                ("S3_BUCKET_NAME", settings.s3_bucket_name),
                ("S3_ACCESS_KEY_ID", settings.s3_access_key_id),
                ("S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key),
            )
            if not v
        ]
        if missing:
            raise ValueError(
                f"S3 backend requires: {', '.join(missing)}"
            )
        from webhook_inspector.infrastructure.storage.s3_blob_storage import (
            S3BlobStorage,
        )

        return S3BlobStorage(
            endpoint_url=settings.s3_endpoint_url,  # type: ignore[arg-type]
            bucket_name=settings.s3_bucket_name,  # type: ignore[arg-type]
            access_key_id=settings.s3_access_key_id,  # type: ignore[arg-type]
            secret_access_key=settings.s3_secret_access_key,  # type: ignore[arg-type]
            region=settings.s3_region,
        )
    raise ValueError(f"unknown blob storage backend: {backend!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/storage/test_factory.py -v`
Expected: PASS.

- [ ] **Step 5: Run full test + lint + type**

Run: `uv run pytest -x && uv run ruff check src/ tests/ && uv run mypy src/`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/webhook_inspector/infrastructure/storage/factory.py \
        tests/unit/storage/test_factory.py
git commit -m "feat(storage): wire S3 backend in factory"
```

---

### Task A7: ~~Validate against Cloud Run~~ — **SKIPPED**

**Originally:** merge to main → deploy to Cloud Run → verify Cloud Trace still receives spans → cut a separate Phase B branch.

**Now skipped** because there are no production users to protect against regression. Phase A stays on `feat/migrate-to-fly`; Phase B continues on the same branch with no intermediate merge. The branch merges once at the end, after Fly is validated end-to-end (after Phase C).

---

## Phase B — Provision Fly infra (no production traffic)

### Task B1: Create the Fly infra directory and Honeycomb/R2 resources

**Files:**
- Create: `infra/fly/README.md`
- Create: `infra/fly/.gitignore`

- [ ] **Step 1: Create the directory**

Run: `mkdir -p /Users/stan/Work/webhook-inspector/infra/fly`

- [ ] **Step 2: Add a `.gitignore` for fly local state**

Create `infra/fly/.gitignore`:
```
*.local.toml
.fly/
```

- [ ] **Step 3: Create Cloudflare R2 bucket**

In the Cloudflare dashboard → R2 → Create bucket `wi-blobs-prod`. Note the account ID and the S3 endpoint URL `https://<account>.r2.cloudflarestorage.com`.

In R2 → Manage R2 API Tokens → Create API token with **Object Read & Write** scope on `wi-blobs-prod`. Save the Access Key ID and Secret Access Key in a password manager.

- [ ] **Step 4: Create the Honeycomb environment**

In Honeycomb UI → Environments → New environment `webhook-inspector-prod`. Copy the API key.

- [ ] **Step 5: Write the README**

Create `infra/fly/README.md`:
````markdown
# Fly.io infra

Three apps deployed in `cdg`:

- `webhook-inspector-db` — self-managed Postgres on a Machine + volume.
- `webhook-inspector-web` — FastAPI app + viewer.
- `webhook-inspector-ingestor` — FastAPI ingestor (webhook receiver).

## Bootstrap from scratch

```bash
cd infra/fly
fly apps create webhook-inspector-db --org personal
fly apps create webhook-inspector-web --org personal
fly apps create webhook-inspector-ingestor --org personal
```

Then for each, set secrets and deploy. See `db.fly.toml`, `web.fly.toml`,
`ingestor.fly.toml`.

## Storage

Blobs are stored in a Cloudflare R2 bucket `wi-blobs-prod`. Set the
S3-compatible credentials via `fly secrets set` on `web` and `ingestor`.

## Observability

Traces and metrics go to Honeycomb via OTLP. Set `OTLP_ENDPOINT` and
`OTLP_HEADERS` per app.

## Cleaner

The cleaner runs as a GitHub Actions cron — see `.github/workflows/cleaner.yml`.
````

- [ ] **Step 6: Commit**

```bash
git add infra/fly/README.md infra/fly/.gitignore
git commit -m "chore(infra): scaffold infra/fly/ directory"
```

---

### Task B2: Deploy self-managed Postgres on Fly

**Files:**
- Create: `infra/fly/db.fly.toml`

- [ ] **Step 1: Create the Fly app**

Run:
```bash
cd /Users/stan/Work/webhook-inspector
fly apps create webhook-inspector-db --org personal
```
Expected: "New app created: webhook-inspector-db".

- [ ] **Step 2: Allocate IPv6 (private; no public IPv4 — PG is only reachable via private network)**

Run: `fly ips allocate-v6 --private --app webhook-inspector-db`
Expected: a `fdaa:…` IPv6 listed.

- [ ] **Step 3: Create the data volume**

Run:
```bash
fly volumes create pg_data \
  --app webhook-inspector-db \
  --region cdg \
  --size 10 \
  --yes
```
Expected: volume created in `cdg`, 10GB.

- [ ] **Step 4: Write the fly.toml**

Create `infra/fly/db.fly.toml`:
```toml
# Self-managed Postgres on Fly Machines.
# Image: flyio/postgres-flex (official Fly PG image, tuned for the platform).
# Backups: snapshots of the pg_data volume (fly volumes snapshots create ...).
# No HA in this config — single primary. Upgrade by stopping the machine,
# creating a new one with the next image tag, and restarting.
app            = "webhook-inspector-db"
primary_region = "cdg"

[build]
  image = "flyio/postgres-flex:16"

[env]
  PRIMARY_REGION = "cdg"

[mounts]
  source      = "pg_data"
  destination = "/data"

[[services]]
  internal_port = 5432
  protocol      = "tcp"

  [[services.ports]]
    port = 5432

[[vm]]
  size   = "shared-cpu-1x"
  memory = "1gb"
```

- [ ] **Step 5: Set the Postgres bootstrap secrets**

Generate a strong password:
```bash
DB_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
echo "Save this: $DB_PASSWORD"
```
Then:
```bash
fly secrets set \
  --app webhook-inspector-db \
  OPERATOR_PASSWORD="$DB_PASSWORD" \
  SU_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)" \
  REPL_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
```
Expected: "Secrets are staged for the first deployment".

- [ ] **Step 6: Deploy the DB**

Run:
```bash
fly deploy --app webhook-inspector-db --config infra/fly/db.fly.toml
```
Expected: machine starts, `pg_data` mounted at `/data`, PG ready in ~30s.

- [ ] **Step 7: Verify PG is reachable on the private network**

Open a temporary VPN to Fly's network:
```bash
fly wireguard create personal cdg my-laptop > ~/Downloads/wi-wg.conf
# import into a WireGuard client and activate
```
Then:
```bash
psql "postgres://postgres:$DB_PASSWORD@webhook-inspector-db.internal:5432/postgres" -c '\l'
```
Expected: list of databases including `postgres`.

- [ ] **Step 8: Create the application database and user**

```bash
psql "postgres://postgres:$DB_PASSWORD@webhook-inspector-db.internal:5432/postgres" <<SQL
CREATE USER wi WITH PASSWORD '$DB_PASSWORD';
CREATE DATABASE webhook_inspector OWNER wi;
GRANT ALL PRIVILEGES ON DATABASE webhook_inspector TO wi;
SQL
```
Expected: "CREATE ROLE", "CREATE DATABASE", "GRANT".

- [ ] **Step 9: Compose the DATABASE_URL**

The URL the app will use:
```
postgresql+psycopg://wi:$DB_PASSWORD@webhook-inspector-db.flycast:5432/webhook_inspector
```
Note: `.flycast` (not `.internal`) gives load-balanced access from other apps in the same org. Save the full URL for the next task.

- [ ] **Step 10: Commit**

```bash
git add infra/fly/db.fly.toml infra/fly/README.md
git commit -m "feat(infra): deploy self-managed Postgres on Fly"
```

---

### Task B3: Deploy the `web` Fly app

**Files:**
- Create: `infra/fly/web.fly.toml`

- [ ] **Step 1: Create the Fly app**

Run: `fly apps create webhook-inspector-web --org personal`
Expected: "New app created".

- [ ] **Step 2: Allocate public IPs**

```bash
fly ips allocate-v4 --shared --app webhook-inspector-web
fly ips allocate-v6 --app webhook-inspector-web
```
Expected: one shared v4 + one dedicated v6 listed.

- [ ] **Step 3: Write the fly.toml**

Create `infra/fly/web.fly.toml`:
```toml
app            = "webhook-inspector-web"
primary_region = "cdg"

[build]
  dockerfile = "../../Dockerfile"

[deploy]
  release_command = "alembic upgrade head"
  strategy        = "rolling"

[processes]
  app = "uvicorn webhook_inspector.web.app.main:app --host 0.0.0.0 --port 8080"

[env]
  PORT                     = "8080"
  ENVIRONMENT              = "prod"
  LOG_LEVEL                = "INFO"
  SERVICE_NAME             = "webhook-inspector"
  BLOB_STORAGE_BACKEND     = "s3"
  S3_REGION                = "auto"
  CLOUD_TRACE_ENABLED      = "false"
  CLOUD_METRICS_ENABLED    = "false"
  OTEL_TRACES_SAMPLER      = "parentbased_traceidratio"
  OTEL_TRACES_SAMPLER_ARG  = "0.1"
  TRACE_SAMPLE_RATIO       = "0.1"

[http_service]
  internal_port        = 8080
  force_https          = true
  auto_stop_machines   = "stop"
  auto_start_machines  = true
  min_machines_running = 0
  processes            = ["app"]

  [http_service.concurrency]
    type       = "requests"
    soft_limit = 100
    hard_limit = 200

  [[http_service.checks]]
    interval     = "15s"
    timeout      = "2s"
    grace_period = "10s"
    method       = "GET"
    path         = "/health"

[[vm]]
  size   = "shared-cpu-1x"
  memory = "512mb"
```

- [ ] **Step 4: Set secrets**

Use the values from Tasks B1 and B2:
```bash
fly secrets set --app webhook-inspector-web \
  DATABASE_URL="postgresql+psycopg://wi:$DB_PASSWORD@webhook-inspector-db.flycast:5432/webhook_inspector" \
  S3_ENDPOINT_URL="https://<account>.r2.cloudflarestorage.com" \
  S3_BUCKET_NAME="wi-blobs-prod" \
  S3_ACCESS_KEY_ID="<r2-access-key>" \
  S3_SECRET_ACCESS_KEY="<r2-secret-key>" \
  OTLP_ENDPOINT="https://api.honeycomb.io" \
  OTLP_HEADERS="x-honeycomb-team=<honeycomb-api-key>,x-honeycomb-dataset=webhook-inspector"
```
Expected: "Secrets are staged for the first deployment".

- [ ] **Step 5: Deploy**

Run: `fly deploy --app webhook-inspector-web --config infra/fly/web.fly.toml`
Expected: image built remotely, `release_command` runs `alembic upgrade head` against the fresh DB (creates all tables incl. `requests` with the v2.5 `search_vector`), machine starts, `/health` returns 200.

- [ ] **Step 6: Smoke test on the `.fly.dev` URL**

```bash
APP_URL="https://webhook-inspector-web.fly.dev"
curl -fsS "$APP_URL/health"  # → 200 {"status":"ok"} or similar
curl -fsS -X POST "$APP_URL/api/endpoints" | tee /tmp/endpoint.json
# Save the token
TOKEN=$(jq -r .token /tmp/endpoint.json)
echo "Token: $TOKEN"
```
Expected: `/health` returns 200, endpoint creation returns a token.

- [ ] **Step 7: Verify a trace lands in Honeycomb**

Trigger a request:
```bash
curl -fsS "$APP_URL/api/endpoints/$TOKEN/requests"
```
Then in Honeycomb UI → Dataset `webhook-inspector` → New query → run over the last 5 min. A span named `GET /api/endpoints/.../requests` should appear.
Expected: trace visible in Honeycomb within ~30s.

- [ ] **Step 8: Commit**

```bash
git add infra/fly/web.fly.toml
git commit -m "feat(infra): deploy web service on Fly"
```

---

### Task B4: Deploy the `ingestor` Fly app

**Files:**
- Create: `infra/fly/ingestor.fly.toml`

- [ ] **Step 1: Create the Fly app and allocate IPs**

```bash
fly apps create webhook-inspector-ingestor --org personal
fly ips allocate-v4 --shared --app webhook-inspector-ingestor
fly ips allocate-v6 --app webhook-inspector-ingestor
```

- [ ] **Step 2: Write the fly.toml**

Create `infra/fly/ingestor.fly.toml`:
```toml
app            = "webhook-inspector-ingestor"
primary_region = "cdg"

[build]
  dockerfile = "../../Dockerfile"

[deploy]
  strategy = "rolling"

[processes]
  app = "uvicorn webhook_inspector.web.ingestor.main:app --host 0.0.0.0 --port 8080"

[env]
  PORT                     = "8080"
  ENVIRONMENT              = "prod"
  LOG_LEVEL                = "INFO"
  SERVICE_NAME             = "webhook-inspector"
  BLOB_STORAGE_BACKEND     = "s3"
  S3_REGION                = "auto"
  CLOUD_TRACE_ENABLED      = "false"
  CLOUD_METRICS_ENABLED    = "false"
  OTEL_TRACES_SAMPLER      = "parentbased_traceidratio"
  OTEL_TRACES_SAMPLER_ARG  = "0.05"
  TRACE_SAMPLE_RATIO       = "0.05"

[http_service]
  internal_port        = 8080
  force_https          = true
  auto_stop_machines   = "stop"
  auto_start_machines  = true
  min_machines_running = 0
  processes            = ["app"]

  [http_service.concurrency]
    type       = "requests"
    soft_limit = 200
    hard_limit = 400

  [[http_service.checks]]
    interval     = "15s"
    timeout      = "2s"
    grace_period = "10s"
    method       = "GET"
    path         = "/health"

[[vm]]
  size   = "shared-cpu-1x"
  memory = "512mb"
```

- [ ] **Step 3: Set secrets** (same set as `web` — same DB, same R2, same Honeycomb)

```bash
fly secrets set --app webhook-inspector-ingestor \
  DATABASE_URL="postgresql+psycopg://wi:$DB_PASSWORD@webhook-inspector-db.flycast:5432/webhook_inspector" \
  S3_ENDPOINT_URL="https://<account>.r2.cloudflarestorage.com" \
  S3_BUCKET_NAME="wi-blobs-prod" \
  S3_ACCESS_KEY_ID="<r2-access-key>" \
  S3_SECRET_ACCESS_KEY="<r2-secret-key>" \
  OTLP_ENDPOINT="https://api.honeycomb.io" \
  OTLP_HEADERS="x-honeycomb-team=<honeycomb-api-key>,x-honeycomb-dataset=webhook-inspector"
# Same shared dataset as web; events are labeled per-service by the
# `service.name` resource attribute set at runtime (`webhook-inspector-ingestor`
# vs `webhook-inspector-app`), so they stay distinguishable in Honeycomb.
```

- [ ] **Step 4: Deploy**

Run: `fly deploy --app webhook-inspector-ingestor --config infra/fly/ingestor.fly.toml`
Expected: machine starts, `/health` returns 200. No `release_command` here — only `web` runs migrations.

- [ ] **Step 5: End-to-end smoke test (web + ingestor + R2)**

```bash
APP_URL="https://webhook-inspector-web.fly.dev"
INGESTOR_URL="https://webhook-inspector-ingestor.fly.dev"
TOKEN=$(curl -sX POST "$APP_URL/api/endpoints" | jq -r .token)
# Send a large payload to exercise R2 offload
dd if=/dev/urandom of=/tmp/big.bin bs=1024 count=50 2>/dev/null
curl -fsS -X POST "$INGESTOR_URL/h/$TOKEN" \
  --data-binary @/tmp/big.bin \
  -H "Content-Type: application/octet-stream"
curl -fsS "$APP_URL/api/endpoints/$TOKEN/requests" | jq .
```
Expected: the request appears in the list with `body_offloaded=true` (since >8KB threshold), and the body is retrievable via the request detail endpoint (proving R2 read works).

- [ ] **Step 6: Commit**

```bash
git add infra/fly/ingestor.fly.toml
git commit -m "feat(infra): deploy ingestor service on Fly"
```

---

### Task B5: Set up the cleaner cron via GitHub Actions

**Files:**
- Create: `.github/workflows/cleaner.yml`

- [ ] **Step 1: Add the GitHub secret**

In GitHub → Settings → Secrets → Actions → New repository secret:
- Name: `FLY_API_TOKEN`
- Value: output of `fly auth token` (run locally).

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/cleaner.yml`:
```yaml
name: cleaner

on:
  schedule:
    - cron: "0 3 * * *"  # daily at 03:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  run-cleaner:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Run cleaner as an ephemeral machine
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        # `fly machine run` signature is: fly machine run [flags] <image> [command...]
        # — image is the first positional, the command + args follow it. The `--`
        # separator stops flyctl flag parsing so `-m` is forwarded to python.
        # (https://fly.io/docs/flyctl/machine-run/)
        run: |
          flyctl machine run \
            --app webhook-inspector-web \
            --rm \
            --region cdg \
            registry.fly.io/webhook-inspector-web:latest \
            -- python -m webhook_inspector.jobs.cleaner
```

- [ ] **Step 3: Manually trigger it to validate**

In GitHub → Actions → cleaner → Run workflow.
Expected: the run completes, logs show `deleted N expired endpoints`. If no endpoints are expired, expects `deleted 0 expired endpoints`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/cleaner.yml
git commit -m "feat(infra): cleaner cron via GitHub Actions + flyctl"
```

---

## Phase C — DNS cutover

### Task C1: Issue TLS certs for the two custom subdomains on Fly

**Files:** none — config via flyctl.

The existing prod setup uses `app.odessa-inspect.org` (web) and `hook.odessa-inspect.org` (ingestor), each as a CNAME to `ghs.googlehosted.com`. We will issue Let's Encrypt certs for **the same two subdomains** on Fly, leaving the apex untouched.

- [ ] **Step 1: Tell Fly about the two subdomains**

```bash
fly certs add app.odessa-inspect.org  --app webhook-inspector-web
fly certs add hook.odessa-inspect.org --app webhook-inspector-ingestor
```
Expected: each command prints a DNS validation record — an `_acme-challenge.<sub>.odessa-inspect.org` TXT, plus the Fly anycast IPs the CNAME/A records will eventually point at.

- [ ] **Step 2: Add the `_acme-challenge` TXT records to Cloudflare**

In the Cloudflare DNS panel for `odessa-inspect.org`, add two TXT records (one per subdomain) exactly as printed by:
```bash
fly certs show app.odessa-inspect.org  --app webhook-inspector-web
fly certs show hook.odessa-inspect.org --app webhook-inspector-ingestor
```
Proxied = OFF (gray cloud).

- [ ] **Step 3: Wait for cert issuance**

```bash
fly certs show app.odessa-inspect.org  --app webhook-inspector-web
fly certs show hook.odessa-inspect.org --app webhook-inspector-ingestor
```
Expected: both report `Status: Ready` within ~5 minutes. If still pending after 15 min, recheck the TXT records.

- [ ] **Step 4: Smoke test the certs via direct IP (before DNS flip)**

```bash
WEB_IP=$(fly ips list --app webhook-inspector-web --json | jq -r '.[] | select(.Type=="v4") | .Address' | head -1)
ING_IP=$(fly ips list --app webhook-inspector-ingestor --json | jq -r '.[] | select(.Type=="v4") | .Address' | head -1)
curl --resolve "app.odessa-inspect.org:443:$WEB_IP"  -fsS "https://app.odessa-inspect.org/health"
curl --resolve "hook.odessa-inspect.org:443:$ING_IP" -fsS "https://hook.odessa-inspect.org/health"
```
Expected: both return 200 — proves the certs are valid even before the CNAME records are flipped.

---

### Task C2: Lower DNS TTL in preparation

**Files:** none — Cloudflare console.

- [ ] **Step 1: Set TTL on the two existing CNAMEs to 1 minute**

In Cloudflare → DNS → records for `odessa-inspect.org`: change the `app` and `hook` CNAME records (currently `→ ghs.googlehosted.com`, TTL 5 min) to TTL `1 min`. The apex `odessa-inspect.org` records stay untouched.

- [ ] **Step 2: Wait at least 1h before the actual flip**

This gives any cached resolver time to learn the lower TTL.

---

### Task C3: Flip DNS to Fly

**Files:** none — Cloudflare console + monitoring.

- [ ] **Step 1: Capture baseline error rate**

In Honeycomb: a query `COUNT WHERE http.status_code >= 500 GROUP BY service.name BUCKET 1m` over the last 1h. Save the link.

- [ ] **Step 2: Update the two CNAMEs in Cloudflare**

Change `app.odessa-inspect.org` CNAME from `ghs.googlehosted.com` → `webhook-inspector-web.fly.dev`.
Change `hook.odessa-inspect.org` CNAME from `ghs.googlehosted.com` → `webhook-inspector-ingestor.fly.dev`.
Proxied still OFF (gray cloud), TTL 1 min from C2.

Why CNAMEs and not A/AAAA: Fly's anycast IPs can change for shared-v4; the `<app>.fly.dev` hostname is the stable handle. The apex `odessa-inspect.org` is unchanged.

- [ ] **Step 3: Monitor for 30 min**

Watch:
- `fly logs --app webhook-inspector-web`
- `fly logs --app webhook-inspector-ingestor`
- Honeycomb 5xx rate
- Cloud Run logs (should see traffic drop to zero over a few minutes as resolvers update)

Expected: traffic on Fly ramps up, Cloud Run goes idle, no 5xx spike.

- [ ] **Step 4: Decision point**

If error rate is comparable to baseline → proceed.
If error rate spikes → **rollback**: in Cloudflare, change the `app` and `hook` CNAME targets back from `webhook-inspector-web.fly.dev` / `webhook-inspector-ingestor.fly.dev` to `ghs.googlehosted.com` (the original Cloud Run domain-mapping target — see `cloud_run_domain_mapping.tf:40`). The Cloud Run domain mappings and certs are still in place because Phase D hasn't run yet, so traffic resumes within the 1-min TTL. Investigate before retrying.

---

### Task C4: 30–60 min observation window

**Files:** none — monitoring only. Shortened from 48h because there are no real users to protect.

- [ ] **Step 1: After 30 min, do a final smoke test**

```bash
curl -fsS https://app.odessa-inspect.org/health
curl -fsS https://hook.odessa-inspect.org/health
TOKEN=$(curl -sX POST https://app.odessa-inspect.org/api/endpoints | jq -r .token)
curl -fsS -X POST "https://hook.odessa-inspect.org/h/$TOKEN" -d 'post-cutover-smoke'
```
Expected: 200s across the board.

- [ ] **Step 2: Quick sanity checks**

- `fly status --app webhook-inspector-web` / `--app webhook-inspector-ingestor` / `--app webhook-inspector-db` all healthy.
- Honeycomb shows traces from both `webhook-inspector-app` and `webhook-inspector-ingestor` services in the last 30 min.
- `fly logs --app webhook-inspector-db` shows no OOM / restart loops.

If anything is off → rollback DNS via C3 step 4 procedure. Otherwise → proceed to Phase D immediately (no 48h wait).

---

## Phase D — Decommission GCP

**Phase ordering note:** `deploy.yml` currently does `working-directory: infra/terraform` and `tofu apply` on every push to `main` (see `deploy.yml:85`, `:91`). If we rename `infra/terraform/` before rewriting the workflow, the next push breaks main. So Phase D order is:
- **D1** — precautionary export (safe, no infra change)
- **D2** — rewrite `deploy.yml` and merge it (so main stops driving tofu)
- **D3** — only then `tofu destroy` and rename the directory
- **D4** — update docs

### Task D1: Final precautionary database export

**Files:** none.

- [ ] **Step 1: Export Cloud SQL one last time**

The Cloud SQL instance name is derived from `locals.tf:11` as `${name_prefix}-pg-${environment}` → `webhook-inspector-pg-dev` (single env, `environment=dev`).

```bash
gcloud sql export sql webhook-inspector-pg-dev \
  gs://<project>-tfstate/exports/cloudsql-final.sql.gz \
  --database=webhook_inspector
```
Expected: export job finishes. Keep this file for ~3 months as a worst-case rollback artifact.

- [ ] **Step 2: Note GCS blob count**

```bash
gsutil du -s gs://<project>-blobs
```
Save the size. Blob data is **not** migrated (fresh-start decision) — endpoints are 7-day TTL, so old blobs would have aged out anyway.

---

### Task D2: Rewrite `deploy.yml` for Fly (must land BEFORE D3 destroys the GCP infra)

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Replace the workflow**

Replace `.github/workflows/deploy.yml` with:
```yaml
name: deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
    steps:
      - uses: actions/checkout@v4

      - uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Deploy web (runs migrations via release_command)
        run: flyctl deploy --remote-only --config infra/fly/web.fly.toml

      - name: Deploy ingestor
        run: flyctl deploy --remote-only --config infra/fly/ingestor.fly.toml

      - name: Smoke test
        run: |
          set -e
          APP_URL="https://app.odessa-inspect.org"
          INGESTOR_URL="https://hook.odessa-inspect.org"

          test "$(curl -s -o /dev/null -w '%{http_code}' ${APP_URL}/health)" = "200" \
            || { echo "app /health failed"; exit 1; }
          test "$(curl -s -o /dev/null -w '%{http_code}' ${INGESTOR_URL}/health)" = "200" \
            || { echo "ingestor /health failed"; exit 1; }

          TOKEN=$(curl -sX POST ${APP_URL}/api/endpoints | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
          STATUS=$(curl -sX POST ${INGESTOR_URL}/h/${TOKEN} -d 'ci-deploy-smoke' -o /dev/null -w '%{http_code}')
          test "$STATUS" = "200" || { echo "smoke test failed with status $STATUS"; exit 1; }

          echo "Deploy successful."
```

- [ ] **Step 2: Push to a branch and verify on `workflow_dispatch`**

```bash
git checkout -b chore/fly-deploy-workflow
git add .github/workflows/deploy.yml
git commit -m "ci: replace gcloud/tofu deploy with flyctl deploy"
git push origin chore/fly-deploy-workflow
gh workflow run deploy.yml --ref chore/fly-deploy-workflow
gh run watch
```
Expected: workflow green — deploys to Fly while Cloud Run still serves DNS-flipped traffic. Once green, main is no longer driving `tofu apply`.

- [ ] **Step 3: Merge to main**

```bash
gh pr create --title "ci: switch deploy workflow to flyctl" --fill
# review, then merge via the GitHub UI
```
Expected: merge succeeds; next push-to-main runs the new Fly workflow, not the old tofu workflow. **D3 is now safe to run.**

---

### Task D3: Tear down GCP resources and archive the terraform directory

**Files:**
- Modify (rename): `infra/terraform/` → `infra/terraform-legacy/`

- [ ] **Step 1: Verify D2 has landed on `main`**

```bash
git fetch origin main
git show origin/main:.github/workflows/deploy.yml | grep -q 'flyctl' \
  && echo "D2 landed, safe to proceed" \
  || { echo "D2 not on main yet — STOP"; exit 1; }
```
Expected: "D2 landed, safe to proceed". This is the gate that prevents breaking main.

- [ ] **Step 2: Destroy Cloud Run services first (stop the cost meter)**

```bash
cd infra/terraform
tofu destroy \
  -target=google_cloud_run_v2_service.app \
  -target=google_cloud_run_v2_service.ingestor \
  -target=google_cloud_run_v2_job.cleaner \
  -target=google_cloud_run_v2_job.migrator \
  -target=google_cloud_run_domain_mapping.app \
  -target=google_cloud_run_domain_mapping.ingestor \
  -auto-approve
```
Expected: services, jobs, and both domain mappings deleted.

- [ ] **Step 3: Destroy Cloud SQL**

```bash
tofu destroy -target=google_sql_database_instance.main -auto-approve
```
Expected: instance deleted. (`deletion_protection = false` already in `cloudsql.tf:11`.)

- [ ] **Step 4: Destroy the rest**

```bash
tofu destroy -auto-approve
```
Expected: GCS bucket (blobs), Artifact Registry, secrets, service accounts, WIF pool, monitoring all deleted. State bucket itself stays (referenced by backend).

- [ ] **Step 5: Rename the directory**

```bash
cd /Users/stan/Work/webhook-inspector
git mv infra/terraform infra/terraform-legacy
```

- [ ] **Step 6: Add a README to the legacy dir**

Create `infra/terraform-legacy/README.md`:
```markdown
# Terraform legacy (GCP — decommissioned 2026-05-XX)

This directory contains the OpenTofu configuration that managed the
GCP deployment (Cloud Run + Cloud SQL + Cloud Trace) before the
migration to Fly.io. Kept for reference and learning value only.

The current infra lives in `infra/fly/`.
```

- [ ] **Step 7: Commit**

```bash
git add infra/terraform-legacy/
git commit -m "chore(infra): archive GCP terraform after Fly cutover"
```

---

### Task D4: Update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update `CLAUDE.md`**

Sections to revise:
- **"Tooling"** — remove "OpenTofu" / "tofu" lines; add "flyctl for Fly.io deploys".
- **"Infra workflow"** — replace the entire block. New content:
  ```markdown
  - All infra changes go through `infra/fly/` (fly.toml files).
  - State is on Fly's side (managed by Fly Machines API). No remote state to configure.
  - Run `fly deploy --config infra/fly/<app>.fly.toml` locally for substantive changes; the `deploy.yml` workflow auto-deploys on push to `main`.
  - Postgres is self-managed on a Fly Machine (`flyio/postgres-flex:16`) — backups via volume snapshots, upgrades by rotating machines.
  - Blobs live in Cloudflare R2 (S3-compatible, free egress).
  ```
- **"Observability"** — replace Cloud Trace references with Honeycomb:
  ```markdown
  - `structlog` for JSON logs, captured by Fly logs.
  - OpenTelemetry traces and metrics export to **Honeycomb** via OTLP when `OTLP_ENDPOINT` is set. Locally and in tests, traces/metrics go to stdout (`ConsoleSpanExporter` / `ConsoleMetricExporter`).
  - Exporter is `opentelemetry-exporter-otlp` (HTTP/protobuf).
  ```

- [ ] **Step 2: Update `README.md` roadmap**

Add a roadmap entry:
```markdown
- **V2.6 / 2026-05** — Migrated from GCP Cloud Run + Cloud SQL to Fly.io
  + self-managed Postgres + Cloudflare R2 + Honeycomb. See
  `docs/superpowers/plans/2026-05-15-migrate-to-fly-io.md`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update CLAUDE.md and README for Fly migration"
```

---

## Post-migration backlog (not in scope)

These are deliberately out of scope for the migration but should be tracked:

- **PG backups** — schedule daily snapshots of the `pg_data` volume via a GHA cron (`fly volumes snapshots create`). Set retention to 14 days.
- **PG monitoring** — install `postgres_exporter` as a sidecar or scrape from Honeycomb Metrics.
- **PG HA** — add a replica machine + promotion script. Optional; ~+€30/mo.
- **Tigris evaluation** — alternative to R2 if Cloudflare proves limiting. Both are S3-compatible so the swap is a secret change.
- **Multi-region read replicas** — Fly makes this trivial (`fly volumes fork --region iad`). Only worth doing if traffic patterns justify it.

---

## Self-review checklist (run after writing the plan)

- ✅ **Spec coverage:** all user-stated requirements covered — Fly.io target (B2–B5), self-managed PG (B2), fresh DB start (B2 step 8 creates a fresh DB, no `pg_dump` import). Code changes for OTEL OTLP (A2, A3) and S3 storage (A4–A6) added because they were necessary prerequisites.
- ✅ **Placeholder scan:** all step bodies contain real code/commands. The `<account>`, `<r2-access-key>`, `<honeycomb-api-key>` placeholders are user-secrets that *must* stay as placeholders (collected in B1).
- ✅ **Type consistency:** `S3BlobStorage`, `OTLPSpanExporter`, `OTLPMetricExporter`, `Settings.otlp_endpoint`, `Settings.s3_*`, `_build_tracer_provider`, `_build_meter_provider` used consistently across A1, A2, A3, A5, A6.

### Review corrections applied (2026-05-15)

- ✅ **Hostnames:** plan now uses `app.odessa-inspect.org` (web) and `hook.odessa-inspect.org` (ingestor), aligned with `README.md:117-119`, `cloud_run_domain_mapping.tf:14-15` and the `app.→hook.` rewrite in `web/app/routes.py:82-83`. Apex `odessa-inspect.org` is explicitly untouched. DNS cutover flips the two existing **CNAMEs**, not A/AAAA.
- ✅ **Phase ordering:** D2 (rewrite `deploy.yml` to flyctl) now precedes D3 (`tofu destroy` + rename `infra/terraform/`). D3 step 1 is a hard gate that verifies D2 landed on `main`. Prevents the "next push-to-main breaks tofu" failure mode.
- ✅ **OTEL singleton:** tracing and metrics each expose a pure `_build_*_provider()` builder that returns a provider **without** calling `set_*_provider()`. Tests assert on builder return values; the global side-effect is covered end-to-end in B3 step 7. Avoids "Overriding ... is not allowed" warnings and stale-provider test failures.
- ✅ **Cloud SQL instance name:** D1 step 1 uses `webhook-inspector-pg-dev` (derived from `locals.tf:11`: `${name_prefix}-pg-${environment}` with `environment=dev`).
- ✅ **OTLP naming:** single convention — Settings field `otlp_endpoint` ↔ env var `OTLP_ENDPOINT`, Settings field `otlp_headers` ↔ env var `OTLP_HEADERS`. The pre-requisites block documents this explicitly so the next agent doesn't reintroduce `OTEL_EXPORTER_OTLP_ENDPOINT`. Phase A intro corrected to match.

### Review corrections applied (2026-05-15, round 2)

- ✅ **SERVICE_NAME doubling:** ingestor `fly.toml` now sets `SERVICE_NAME = "webhook-inspector"` (not `"webhook-inspector-ingestor"`). The runtime suffixes `-ingestor` / `-app` in `web/ingestor/main.py:17,25` and `web/app/main.py:25,33`, so the final values are `webhook-inspector-ingestor` and `webhook-inspector-app` — no doubling. Both services share the Honeycomb dataset `webhook-inspector`, distinguished by the `service.name` resource attribute.
- ✅ **Rollback procedure:** C3 step 4 now reverts the two CNAMEs to `ghs.googlehosted.com` (the actual original target in `cloud_run_domain_mapping.tf:40`), not "Cloud Run IPs". Mentions that Cloud Run domain mappings + certs are still alive because Phase D is gated on the 48h observation window.
- ✅ **Phase A intro naming:** line 32 updated from `OTEL_EXPORTER_OTLP_ENDPOINT` to `OTLP_ENDPOINT` to align with the naming-conventions block.

### Review corrections applied (2026-05-15, round 3)

- ✅ **`fly machine run` syntax:** B5 cleaner workflow rewritten to the actual CLI signature `fly machine run [flags] <image> [command...]`. Image is now positional (no `--image` flag — it doesn't exist), and the command (`python -m webhook_inspector.jobs.cleaner`) is passed after a `--` separator so `-m` is not consumed by flyctl flag parsing. Verified against https://fly.io/docs/flyctl/machine-run/. Docker image's `CMD` is overridden by the trailing positional args (no `ENTRYPOINT` in the Dockerfile).
