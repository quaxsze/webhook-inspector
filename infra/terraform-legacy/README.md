# Terraform legacy (GCP — decommissioned 2026-05-15)

> **⚠️ This directory is archived.** Production runs on Fly.io since 2026-05-15.
> The configuration here is kept as a reference of how the GCP deployment
> looked. **Do not run `tofu apply` from here** — the corresponding GCP
> resources have all been destroyed and the state bucket is unused.
>
> Current infra : `infra/fly/`. See `docs/superpowers/plans/2026-05-15-migrate-to-fly-io.md` for the full migration story.

---

Terraform module that previously deployed webhook-inspector to GCP in a single `dev` env.

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

## Continuous Deployment

After Phase C, deploys are automated via GitHub Actions:
- Push to `main` triggers `.github/workflows/deploy.yml`
- Build image with git SHA tag → push to Artifact Registry → execute migrator Job → `tofu apply -target=<Cloud Run resources>` → smoke test

No manual `./scripts/build_and_push.sh` needed in normal flow. Use the script only for emergency hotfixes or local image testing.

**Required GitHub variables (set once):**
- `GCP_PROJECT_ID`
- `GCP_REGION`
- `GCP_WIF_PROVIDER`
- `GCP_DEPLOYER_SA`

**No GitHub secrets needed for the deploy workflow** — auth is via Workload Identity Federation.

**Other secrets (used only when Terraform runs locally):**
- `CLOUDFLARE_API_TOKEN` (also a GH secret; not consumed by `deploy.yml` since it doesn't target Cloudflare resources)

## Custom Domain Setup

Production URLs:
- App: `https://app.<your-domain>`
- Ingestor: `https://hook.<your-domain>`

To re-do the DNS setup:
1. Buy a domain (Cloudflare Registrar recommended — at-cost pricing)
2. Set `TF_VAR_cloudflare_api_token` env var locally
3. Add `domain` + `cloudflare_zone_id` to `terraform.tfvars`
4. `gcloud domains verify <domain>` once (manual, interactive)
5. `tofu apply` — creates Cloud Run domain mappings + Cloudflare CNAMEs
6. Wait 5-30 min for Google-managed TLS certs to provision

## Monitoring & alerting

Dashboard URL (after `tofu apply`):

```bash
cd infra/terraform
tofu output dashboard_url
```

Alerts active :

- **High p95 ingest latency** — capture_duration p95 > 1s for 5 min
- **High 5xx rate (ingestor)** — Cloud Run 5xx requests > threshold for 5 min
- **Cloud SQL CPU > 70% sustained (10min)** — tier-upgrade signal (db-f1-micro → db-custom-1-1740)
- **Cloud SQL query latency p95 > 200ms (5min)** — tier-upgrade signal; relies on Cloud SQL Insights (enabled in `cloudsql.tf`)
- **Cloud SQL disk pressure** — disk > 90%
- **Cleaner stale** — no heartbeat in 26h

All routed to `owner_email` via a single notification channel.

### Manual drill

Force a 5xx surge to validate the alert :

```bash
# Temporarily disable Cloud SQL (returns 5xx on every ingest)
gcloud sql instances patch webhook-inspector-pg-dev --activation-policy=NEVER
sleep 300  # 5 min — let the alert fire
# Check email + alert console
gcloud sql instances patch webhook-inspector-pg-dev --activation-policy=ALWAYS
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
