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
