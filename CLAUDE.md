# Claude Code conventions for webhook-inspector

This file is loaded automatically by Claude Code when working in this repo. It documents the conventions the maintainer expects any AI-assisted work to follow.

## Commit messages

- **No `Co-Authored-By: Claude` trailer.** AI assistance is disclosed in the README; we keep it off individual commits.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `style:`
- Scopes encouraged: `feat(web):`, `fix(infra):`, `test(domain):`
- One commit per logical change. Frequent small commits over one big one.

## Tooling

- **OpenTofu** (`tofu`), not Terraform — Homebrew dropped Terraform after the BSL license change; OpenTofu is the drop-in fork.
- **uv** for Python deps: `uv add`, `uv sync`, `uv run` — never `pip install` directly.
- **pre-commit** is installed — `git commit` runs ruff format + ruff check + a few hygiene hooks automatically. If a hook reformats, re-stage and re-commit.
- **Make targets**: `make lint`, `make type`, `make test`, `make up`, `make down`, `make migrate`, `make clean`.

## Metrics conventions (V2+)

- Use cases depend on `domain/ports/metrics_collector.py:MetricsCollector` ABC, never on OTEL directly.
- Adapter `infrastructure/observability/otel_metrics_collector.py` wraps the OTEL Meter.
- Cardinality is strict — labels limited to `method` (uppercase HTTP verb), `body_offloaded` (bool), `success` (bool). No label may include user-controlled values (token, IP, endpoint_id).
- New metrics go through code review : think about cardinality before adding any label.
- Short-lived jobs (cleaner, migrator) must call `force_flush_metrics()` before exit, or datapoints are lost.
- Heartbeat counters (always +1 per run) are required for absence-based alerts to work reliably.

## Development discipline

- **Test-Driven Development**: write the failing test first, run it to confirm it fails, write the minimum code to pass, run it to confirm it passes, then commit.
- **Clean Architecture layers**: `domain → application → infrastructure → web`. Domain has zero external dependencies. Use cases depend on port interfaces (ABCs), not concrete implementations.
- **Mock the network, not internals**. MSW for frontend, in-memory FakeRepo ABCs for backend use cases. Integration tests hit a real Postgres via testcontainers.
- **Module-level side effects are forbidden** in `web/app/main.py` and `web/ingestor/main.py`. Use the FastAPI `lifespan` async context manager for `Settings()` and observability setup. (Phase C lesson: side effects at import break CI test collection.)

## Infra workflow

- All infra changes go through Terraform (`infra/terraform/`).
- State is in the GCS backend (`<project>-tfstate` bucket).
- `tofu apply` locally for substantive changes; the `deploy.yml` workflow auto-applies the Cloud Run resources on `push: main` (it uses `-target=` to skip Cloudflare/domain resources which need a real token).
- Cloud SQL is `db-f1-micro` with explicit `edition = "ENTERPRISE"` — GCP defaults new instances to `ENTERPRISE_PLUS` which rejects the legacy tier.
- Cloud Run Jobs gen2 require minimum `memory = "512Mi"`.

## Domain / DNS

- Production domain: `odessa-inspect.org`, hosted via Cloudflare Registrar (DNS delegated automatically).
- Cloudflare records are in **DNS-only mode** (gray cloud), `proxied = false`. TLS is Google-managed at Cloud Run.
- Custom DNS resolvers (NextDNS, etc.) may block the domain locally — use `curl --resolve` or whitelist when debugging.

## Observability

- `structlog` for JSON logs. `service.name` field is populated automatically via a logging filter.
- OpenTelemetry traces export to **Cloud Trace** when `CLOUD_TRACE_ENABLED=true` (production). Locally and in tests, traces go to stdout via `SimpleSpanProcessor` to avoid the pytest-stdout-close race condition.
- Exporter is `opentelemetry-exporter-gcp-trace` (uses ADC), **not** raw OTLP.

## What this project IS

- A learning side-project to practice modern DevOps on GCP.
- AI-assisted, transparently — see README disclosure.
- Single env (`dev` acts as prod). No `prod` workspace yet.
- Owner-only — contributions welcome, please open an issue first.

## What this project is NOT

- A commercial product. Free, no signup, URLs expire after 7 days.
- A reference architecture. Choices favor learning over enterprise-grade rigor.
- A multi-env / multi-tenant system (V5+ if ever).

## Roadmap

See README. Current state: **V1 Live** (MVP + CI/CD + custom domain + Cloud Trace). Next planned: V2 (custom response + custom OTEL metrics + dashboards).
