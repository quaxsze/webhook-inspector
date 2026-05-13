# Webhook Inspector

[![CI](https://github.com/quaxsze/webhook-inspector/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/quaxsze/webhook-inspector/actions/workflows/lint-and-test.yml)
[![Deploy](https://github.com/quaxsze/webhook-inspector/actions/workflows/deploy.yml/badge.svg)](https://github.com/quaxsze/webhook-inspector/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/types-mypy_strict-blue.svg)](https://mypy.readthedocs.io/)

A self-hostable webhook inspection service. Generate a URL, point any webhook at it, see requests in real-time in your browser.

> **AI-assisted development.** Parts of this codebase were drafted with Claude (Anthropic) acting as a pair programmer. All design decisions, architectural reviews, debugging, and verification are mine. See [`docs/plans/`](docs/plans/) and [`docs/specs/`](docs/specs/) for the design process — the goal is to learn DevOps in public, transparently.

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

## Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| V1 | ✅ Live | MVP: 5 endpoints + live viewer + Cloud Run + WIF CI/CD + custom domain + Cloud Trace |
| V2 | ✅ Live | Custom response + copy-as-curl + custom OTEL metrics + Cloud Monitoring dashboards + alerting |
| V3 | 🟡 Planned | Forward webhook to a target URL (Pub/Sub + worker + DLQ + retry) |
| V4 | 🟡 Planned | Rate limiting + Cloudflare WAF + Memorystore Redis |
| V5 | 🟡 Planned | Google OAuth auth + claimed URLs + long-term history |
| V6 | 🟡 Planned | Formal SLOs + error budgets + status page |

See [`docs/specs/`](docs/specs/) for design rationale per phase.

## Contributing

Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). For security issues, please use [GitHub Security Advisories](https://github.com/quaxsze/webhook-inspector/security/advisories/new) (see [`SECURITY.md`](SECURITY.md)).

## License

[MIT](LICENSE) © 2026 Stanislas Plum
