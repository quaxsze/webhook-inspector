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
