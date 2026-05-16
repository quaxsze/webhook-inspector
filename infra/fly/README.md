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
S3-compatible credentials via `fly secrets set` on `web` and `ingestor`:

```bash
fly secrets set --app webhook-inspector-web \
  S3_ENDPOINT_URL="https://<account>.r2.cloudflarestorage.com" \
  S3_BUCKET_NAME="wi-blobs-prod" \
  S3_ACCESS_KEY_ID="<r2-access-key>" \
  S3_SECRET_ACCESS_KEY="<r2-secret-key>"
```

## Observability

Traces and metrics go to Honeycomb via OTLP. Set `OTLP_ENDPOINT` and
`OTLP_HEADERS` per app:

```bash
fly secrets set --app webhook-inspector-web \
  OTLP_ENDPOINT="https://api.honeycomb.io" \
  OTLP_HEADERS="x-honeycomb-team=<honeycomb-api-key>,x-honeycomb-dataset=webhook-inspector"
```

## Database

`DATABASE_URL` points to the self-managed Postgres via Fly's private mesh:

```
postgresql+psycopg://wi:<password>@webhook-inspector-db.flycast:5432/webhook_inspector
```

## Cleaner

The cleaner runs as a GitHub Actions cron — see `.github/workflows/cleaner.yml`.
