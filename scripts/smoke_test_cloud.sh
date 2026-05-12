#!/usr/bin/env bash
# End-to-end smoke test on deployed Cloud Run services.

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <project-id>}"
REGION="europe-west1"

APP_URL=$(gcloud run services describe webhook-inspector-app --region="$REGION" --format="value(status.url)")
INGESTOR_URL=$(gcloud run services describe webhook-inspector-ingestor --region="$REGION" --format="value(status.url)")

echo "==> App URL: $APP_URL"
echo "==> Ingestor URL: $INGESTOR_URL"

echo ""
echo "==> Step 1: Create endpoint"
RESPONSE=$(curl -sX POST "${APP_URL}/api/endpoints")
echo "$RESPONSE" | python3 -m json.tool
TOKEN=$(echo "$RESPONSE" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo "Token: $TOKEN"

echo ""
echo "==> Step 2: Send 3 webhooks to ingestor"
for i in 1 2 3; do
  STATUS=$(curl -sX POST "${INGESTOR_URL}/h/${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"i\":$i}" \
    -o /dev/null -w "%{http_code}")
  echo "Webhook $i: HTTP $STATUS"
done

echo ""
echo "==> Step 3: List captured requests"
curl -s "${APP_URL}/api/endpoints/${TOKEN}/requests" | python3 -m json.tool

echo ""
echo "==> Step 4: Viewer URL (open in browser):"
echo "${APP_URL}/${TOKEN}"
