# Webhook Inspector

[![CI](https://github.com/hooktrace-io/hooktrace/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/hooktrace-io/hooktrace/actions/workflows/lint-and-test.yml)
[![Deploy](https://github.com/hooktrace-io/hooktrace/actions/workflows/deploy.yml/badge.svg)](https://github.com/hooktrace-io/hooktrace/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/types-mypy_strict-blue.svg)](https://mypy.readthedocs.io/)

A self-hostable webhook inspection service. Generate a URL, point any webhook at it, see requests in real-time in your browser.

> **AI-assisted development.** Parts of this codebase were drafted with Claude (Anthropic) acting as a pair programmer. All design decisions, architectural reviews, debugging, and verification are mine.

## Architecture

```
                       ┌──────────────────────┐
                       │  Cloudflare DNS      │
                       │  app.hooktrace.io    │
                       │  hook.hooktrace.io   │
                       └──────────┬───────────┘
                                  │
              ┌───────────────────┴────────────────────┐
              ▼                                        ▼
      ┌──────────────┐                         ┌──────────────┐
      │  Fly Machine │                         │  Fly Machine │
      │  "web"       │                         │  "ingestor"  │
      │              │                         │              │
      │  FastAPI +   │                         │  FastAPI +   │
      │  Jinja2 +    │                         │  body limits │
      │  HTMX + SSE  │                         │              │
      └──────┬───────┘                         └──────┬───────┘
             │                                        │
             │   ┌────────────────────────────────────┤
             │   │                                    │
             ▼   ▼                                    ▼
      ┌──────────────────┐                  ┌──────────────────┐
      │  Fly Postgres    │  LISTEN/NOTIFY   │  Cloudflare R2   │
      │  (self-managed)  │  ◄────────────►  │  body offload    │
      │  Postgres 16     │                  │  > 8 KB          │
      └──────────────────┘                  └──────────────────┘
              ▲
              │
      ┌───────┴──────────┐         ┌──────────────────────────┐
      │ GH Actions cron  │         │ OTLP/HTTP → Honeycomb    │
      │ "cleaner"        │         │ (traces + metrics)       │
      │ (daily 03:00 UTC)│         │ + structlog → fly logs   │
      └──────────────────┘         └──────────────────────────┘
```

**Two FastAPI services + one scheduled job sharing one Python package:**

- `web` — viewer UI + REST API + SSE stream (Fly Machine, min=1 for warm SSE)
- `ingestor` — public webhook capture (Fly Machine, autoscaled)
- `cleaner` — daily GitHub Actions cron, deletes expired endpoints via `flyctl machine run --rm`
- Migrations run as `release_command = "alembic upgrade head"` before each web revision is promoted

Stack: Python 3.13 + FastAPI + SQLModel + Fly Machines + self-managed Fly Postgres + Cloudflare R2 + OpenTelemetry (OTLP/HTTP → Honeycomb) + GitHub Actions.

The data flow on a webhook capture:

1. Client POSTs to `https://hook.hooktrace.io/h/{token}`
2. `ingestor` looks up the endpoint, captures method/headers/body/source IP
3. Bodies > 8 KB offloaded to Cloudflare R2, smaller ones inline in Postgres
4. INSERT + `pg_notify('new_request', '...')` in one atomic transaction
5. `web`'s SSE handlers listening on Postgres NOTIFY receive the request_id
6. Each open `/stream/{token}` connection that matches receives an HTML fragment over Server-Sent Events
7. HTMX in the browser inserts the fragment at the top of the live list

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

For faster iteration with hot reload:

```bash
make dev-postgres
# In a second terminal:
export DATABASE_URL=postgresql+psycopg://webhook:webhook@localhost:5434/webhook_inspector
make dev-app
# In a third terminal:
make dev-ingestor
```

This runs the FastAPI services locally with `uvicorn --reload` so code changes take effect without rebuilding Docker images.


## Production deployment

Live URLs:
- App: `https://app.hooktrace.io`
- Ingestor (webhook target): `https://hook.hooktrace.io`

Generated webhook URLs (`POST /api/endpoints`) automatically point to the ingestor subdomain. Use as-is in any service that sends webhooks (Stripe, GitHub, Slack...).

Deploys are automatic on push to `main` via `.github/workflows/deploy.yml` (`flyctl deploy --remote-only` on each service). See `infra/fly/README.md` for the deployment topology.

Trace data is exported via OTLP/HTTP — point `OTLP_ENDPOINT` at any OTLP backend (Honeycomb, Grafana Cloud, etc.) and traces ship there. Without `OTLP_ENDPOINT`, spans go to stdout and are visible in `fly logs`.

## Custom response

By default a captured webhook gets `200 OK` with body `{"ok":true}`. You can customize this when creating an endpoint:

```bash
curl -X POST https://app.hooktrace.io/api/endpoints \
  -H 'Content-Type: application/json' \
  -d '{
    "response": {
      "status_code": 201,
      "body": "{\"created\":true}",
      "headers": {"Content-Type": "application/json"},
      "delay_ms": 0
    }
  }'
```

Constraints:
- `status_code` in `[100, 599]`
- `delay_ms` in `[0, 30000]`
- `body` up to 64 KiB
- `headers` cannot override `Content-Length`, `Transfer-Encoding`, `Connection`, `Host`, `Date`

You can also configure all of this via the landing page's "Advanced options" disclosure.

## Vanity URL slug

```bash
curl -X POST https://app.hooktrace.io/api/endpoints \
  -H 'Content-Type: application/json' \
  -d '{"slug": "my-stripe-test"}'
```

Constraints:
- 3–32 chars, lowercase letters / digits / hyphens, no leading/trailing hyphen
- Reserved slugs (`api`, `health`, `stripe`, `github`, …) return 400
- Already-claimed slugs return 409

Without `slug`, you still get a random 22-char token (V1 behavior).

## Search captured requests

```bash
curl "https://app.hooktrace.io/api/endpoints/$TOKEN/requests?q=payment_intent.succeeded"
```

Searches across method, path, body (first 8 KB), and headers. Powered by Postgres `tsvector` + GIN index.

Notes / limitations:
- **AND semantics**: `q=foo bar` matches rows containing BOTH `foo` AND `bar` (any order). Not phrase search.
- **Hyphenated tokens split**: the `simple` tsearch config tokenizes on `-`, so `x-stripe-signature` is indexed as three tokens (`x`, `stripe`, `signature`). Search the full header name and you'll match via AND.
- **Slash-prefixed paths kept whole**: `/health` is indexed as the single token `'/health'` (the leading `/` is preserved). Search for `/health` (with the slash) to match it; bare `health` won't unless it also appears in body/headers.
- **8 KB body cap**: bodies offloaded to GCS (> 8 KB) aren't searchable.
- **Live updates don't honor active search**: requests captured during a search session aren't auto-filtered. Re-submit the query to refresh.

## Export captured requests

```bash
curl -OJ "https://app.hooktrace.io/api/endpoints/$TOKEN/export.json"
```

Streams a single JSON file with full bodies (including bodies offloaded to GCS, fetched on-the-fly). Cap: 10 000 requests per export (`EXPORT_MAX_REQUESTS` env override). Beyond the cap returns 413; filter-then-export will land in V3.

Response format:

```json
{
  "endpoint": {
    "token": "my-stripe-test",
    "created_at": "...",
    "expires_at": "...",
    "response": { "status_code": 200, "body": "...", "headers": {}, "delay_ms": 0 }
  },
  "exported_at": "...",
  "exported_request_count": 142,
  "requests": [
    {
      "id": "...",
      "method": "POST",
      "path": "/",
      "headers": {...},
      "body": "...full body, inlined from DB or fetched from GCS...",
      "body_size": 1234,
      "received_at": "..."
    }
  ]
}
```

`requests` are ordered most-recent-first. `exported_request_count` is the count of rows in the array, not the endpoint's lifetime counter.

## Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| V1 | ✅ Live | MVP : 5 endpoints + live viewer + Cloud Run + WIF CI/CD + custom domain + Cloud Trace |
| V2 | ✅ Live | Custom response (status/body/headers/delay) + copy-as-curl + custom OTEL metrics + Cloud Monitoring dashboards + alerting |
| V2.5 | ✅ Live | **UX produit** — vanity URL slug + search/filter (Postgres `tsvector` + GIN index) + export captured requests as JSON |
| V2.6 | ✅ Live | **Migration cloud** — GCP (Cloud Run + Cloud SQL + GCS + Cloud Trace) → Fly.io (Machines + self-managed Postgres + Cloudflare R2) + OTLP traces. |
| V3 | 🟡 Planned | **Observability pivot** — HMAC validation (9 services) + per-integration view + schema drift + replay + OTEL timeline + forward to 1 target URL (Pro) with retry + DLQ |
| V4 | 🟡 Planned | **Production hardening** — multi-region read replicas + HA Postgres pair + formal SLOs + transform JSONata (Pro) + multi-target fan-out (Team) |
| V5 | 🟡 Planned | **Auth + power user** — Google OAuth + claimed URLs + activity log per-account + statistics charts + API tokens + (optional) DNSBL lookup |
| V6 | 🟡 Planned | Formal SLOs + error budgets + status page publique + first real postmortem |
| V7+ | 🟡 Future | WebSocket inspection (new protocol dimension) + SMTP/email capture (new service infra) — explored as desire dictates |

See [`docs/specs/`](docs/specs/) for design rationale for upcoming phases.

## Contributing

Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). For security issues, please use [GitHub Security Advisories](https://github.com/hooktrace-io/hooktrace/security/advisories/new) (see [`SECURITY.md`](SECURITY.md)).

## License

[MIT](LICENSE) © 2026 Stanislas Plum
