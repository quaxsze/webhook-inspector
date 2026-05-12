#!/usr/bin/env bash
# Bootstrap GCP project for webhook-inspector:
# - Enable required APIs
# - Create Terraform state bucket
#
# Usage: ./scripts/bootstrap_gcp.sh <project-id>
#
# Idempotent: safe to run multiple times.

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <project-id>}"
REGION="europe-west1"
STATE_BUCKET="${PROJECT_ID}-tfstate"

echo "==> Setting project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

echo "==> Enabling APIs (this can take 1-2 min)..."
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  iam.googleapis.com \
  compute.googleapis.com \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com

echo "==> Creating Terraform state bucket: $STATE_BUCKET"
if gcloud storage buckets describe "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  echo "    Bucket already exists. Skipping."
else
  gcloud storage buckets create "gs://${STATE_BUCKET}" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
  gcloud storage buckets update "gs://${STATE_BUCKET}" \
    --versioning  # keep history of state changes
fi

echo "==> Done. Terraform state bucket: gs://${STATE_BUCKET}"
echo "==> Next: cd infra/terraform && terraform init"
