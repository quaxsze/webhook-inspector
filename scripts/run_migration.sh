#!/usr/bin/env bash
# Run alembic migrations against Cloud SQL via cloud-sql-proxy.
#
# Usage: ./scripts/run_migration.sh <project-id>

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <project-id>}"
REGION="europe-west1"
INSTANCE="webhook-inspector-pg-dev"
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${INSTANCE}"
DB_NAME="webhook_inspector"
DB_USER="webhook"
LOCAL_PORT="5435"

echo "==> Fetching DB password from Secret Manager..."
# DATABASE_URL has full conn string; extract password.
DATABASE_URL=$(gcloud secrets versions access latest --secret=database-url --project="$PROJECT_ID")
DB_PASSWORD=$(echo "$DATABASE_URL" | sed -E 's|^.*://[^:]+:([^@]+)@.*$|\1|')

echo "==> Starting cloud-sql-proxy on localhost:${LOCAL_PORT}..."
cloud-sql-proxy --port "$LOCAL_PORT" "$CONNECTION_NAME" &
PROXY_PID=$!
trap "kill $PROXY_PID 2>/dev/null || true" EXIT

# Wait for proxy ready
echo "==> Waiting for cloud-sql-proxy to be ready..."
for _ in $(seq 1 30); do
  if pg_isready -h localhost -p "$LOCAL_PORT" -U "$DB_USER" >/dev/null 2>&1; then
    echo "    Proxy ready"
    break
  fi
  sleep 0.5
done

echo "==> Running alembic upgrade head..."
PGPASSWORD="$DB_PASSWORD" DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@localhost:${LOCAL_PORT}/${DB_NAME}" \
  uv run alembic upgrade head

echo "==> Done. Tables:"
PGPASSWORD="$DB_PASSWORD" psql -h localhost -p "$LOCAL_PORT" -U "$DB_USER" -d "$DB_NAME" -c "\dt"
