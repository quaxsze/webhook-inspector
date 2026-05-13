# Webhook Inspector

[![CI](https://github.com/quaxsze/webhook-inspector/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/quaxsze/webhook-inspector/actions/workflows/lint-and-test.yml)
[![Deploy](https://github.com/quaxsze/webhook-inspector/actions/workflows/deploy.yml/badge.svg)](https://github.com/quaxsze/webhook-inspector/actions/workflows/deploy.yml)
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
                       │  app.<domain>        │
                       │  hook.<domain>       │
                       └──────────┬───────────┘
                                  │
              ┌───────────────────┴────────────────────┐
              ▼                                        ▼
      ┌──────────────┐                         ┌──────────────┐
      │  Cloud Run   │                         │  Cloud Run   │
      │  "app"       │                         │  "ingestor"  │
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
      │   Cloud SQL      │  LISTEN/NOTIFY   │  Cloud Storage   │
      │   Postgres 16    │  ◄────────────►  │  body offload    │
      │   (db-f1-micro)  │                  │  > 8 KB          │
      └──────────────────┘                  └──────────────────┘
              ▲
              │
      ┌───────┴──────────┐         ┌──────────────────────────┐
      │ Cloud Run Job    │         │ OTEL → Cloud Trace +     │
      │ "cleaner"        │         │       Cloud Monitoring   │
      │ (cron 3 AM UTC)  │         │ + structlog → Logging    │
      └──────────────────┘         └──────────────────────────┘
```

**Two FastAPI services + two Cloud Run Jobs sharing one Python package:**

- `app` — viewer UI + REST API + SSE stream (min=1 for warm SSE)
- `ingestor` — public webhook capture (min=0, scales up to 20)
- `cleaner` — daily job, deletes expired endpoints
- `migrator` — runs alembic migrations on each deploy

Stack: Python 3.13 + FastAPI + SQLModel + Cloud Run gen2 + Cloud SQL + Cloud Storage + Cloud Trace + Cloud Monitoring + Terraform/OpenTofu + GitHub Actions + Workload Identity Federation.

The data flow on a webhook capture:

1. Client POSTs to `https://hook.<domain>/h/{token}`
2. `ingestor` looks up the endpoint, captures method/headers/body/source IP
3. Bodies > 8 KB offloaded to GCS, smaller ones inline in Postgres
4. INSERT + `pg_notify('new_request', '...')` in one atomic transaction
5. `app`'s SSE handlers listening on Postgres NOTIFY receive the request_id
6. Each open `/stream/{token}` connection that matches receives an HTML fragment over Server-Sent Events
7. HTMX in the browser inserts the fragment at the top of the live list

See spec at `docs/specs/2026-05-11-webhook-inspector-design.md`.

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
- App: `https://app.odessa-inspect.org`
- Ingestor (webhook target): `https://hook.odessa-inspect.org`

Generated webhook URLs (`POST /api/endpoints`) automatically point to the ingestor subdomain. Use as-is in any service that sends webhooks (Stripe, GitHub, Slack...).

Deploys are automatic on push to `main`. See `infra/terraform/README.md` for the deployment pipeline.

Trace data is exported to Google Cloud Trace. View traces:
```
gcloud trace traces list --limit=10
```

## Custom response

By default a captured webhook gets `200 OK` with body `{"ok":true}`. You can customize this when creating an endpoint:

```bash
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
```

Constraints:
- `status_code` in `[100, 599]`
- `delay_ms` in `[0, 30000]`
- `body` up to 64 KiB
- `headers` cannot override `Content-Length`, `Transfer-Encoding`, `Connection`, `Host`, `Date`

You can also configure all of this via the landing page's "Advanced options" disclosure.

## Vanity URL slug

```bash
curl -X POST https://app.odessa-inspect.org/api/endpoints \
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
curl "https://app.odessa-inspect.org/api/endpoints/$TOKEN/requests?q=payment_intent.succeeded"
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
curl -OJ "https://app.odessa-inspect.org/api/endpoints/$TOKEN/export.json"
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
| V3 | 🟡 Planned | **Forward webhook to target(s)** — URL + Slack + Email (Pub/Sub topic + worker + dead-letter queue + exponential retry + idempotency keys) |
| V4 | 🟡 Planned | Rate limiting + Cloudflare WAF custom rules + Memorystore Redis (distributed counters) |
| V5 | 🟡 Planned | **Auth + power user** — Google OAuth + claimed URLs + activity log per-account + statistics charts + API tokens + (optional) DNSBL lookup |
| V6 | 🟡 Planned | Formal SLOs + error budgets + status page publique + first real postmortem |
| V7+ | 🟡 Future | WebSocket inspection (new protocol dimension) + SMTP/email capture (new service infra) — explored as desire dictates |

See [`docs/specs/`](docs/specs/) for design rationale per phase.

## Contributing

Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). For security issues, please use [GitHub Security Advisories](https://github.com/quaxsze/webhook-inspector/security/advisories/new) (see [`SECURITY.md`](SECURITY.md)).

## License

[MIT](LICENSE) © 2026 Stanislas Plum
