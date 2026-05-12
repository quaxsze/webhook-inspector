# Infrastructure — webhook-inspector (Phase B)

Terraform module deploying webhook-inspector to GCP in a single `dev` env.

> This project uses [OpenTofu](https://opentofu.org/) (the BSL-free fork of Terraform). All HCL is fully compatible with Terraform >= 1.6 if you prefer.

## Prerequisites

- GCP project created with billing enabled and a budget alert.
- `gcloud` CLI authenticated (`gcloud auth login` + `gcloud auth application-default login`).
- OpenTofu >= 1.10.
- Docker (for building images).

## First-time setup

```bash
# 1. Bootstrap APIs + state bucket (run from repo root)
./scripts/bootstrap_gcp.sh <project-id>

# 2. Set up Terraform vars
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set project_id to your actual GCP project ID

# 3. Initialize OpenTofu
tofu init -backend-config="bucket=<project-id>-tfstate"

# 4. Build and push the first image (from repo root)
cd ../..
./scripts/build_and_push.sh <project-id>
# Note the tag printed at the end and update image_tag in terraform.tfvars.

# 5. Apply
cd infra/terraform
tofu apply

# 6. Run migrations
cd ../..
./scripts/run_migration.sh <project-id>

# 7. Smoke test
./scripts/smoke_test_cloud.sh <project-id>
```

## Updating

```bash
# After pushing a new image:
./scripts/build_and_push.sh <project-id> v2
# Update image_tag in terraform.tfvars to v2 (or the new SHA).
cd infra/terraform
tofu apply
```

## Tearing down

```bash
cd infra/terraform
tofu destroy
# This removes Cloud Run, Cloud SQL (with all data!), GCS bucket, etc.
# The state bucket itself is NOT destroyed — delete manually if needed.
```

## Files

- `versions.tf` — provider versions
- `backend.tf` — GCS backend
- `variables.tf` / `locals.tf` — inputs and derived names
- `apis.tf` — required GCP APIs
- `service_accounts.tf` — runtime SAs + IAM
- `cloudsql.tf` — Postgres instance
- `secret_manager.tf` — DATABASE_URL
- `gcs.tf` — blob bucket
- `artifact_registry.tf` — Docker repo
- `cloud_run_ingestor.tf` / `cloud_run_app.tf` / `cloud_run_cleaner.tf` — services + job
- `cloud_scheduler.tf` — cron trigger
- `outputs.tf` — exposed URLs

## Cost (dev env, ~side-project usage)

- Cloud SQL `db-f1-micro` : ~9 €/month (after free trial)
- Cloud Run : free tier covers most small projects (< 2M req/month, < 360k vCPU-s)
- GCS : negligible (< 1 GB)
- Artifact Registry : 0.5 GB free, then ~0.10 €/GB
- Cloud Scheduler : 3 jobs free
- Secret Manager : 6 secrets free

**Total : ~10-15 €/month**. Budget alert at €20 catches overruns.
