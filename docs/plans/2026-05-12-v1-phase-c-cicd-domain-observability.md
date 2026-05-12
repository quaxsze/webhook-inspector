# Webhook Inspector V1 — Phase C : CI/CD + Domaine + Observabilité

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** automatiser le déploiement (push → prod), exposer l'app sous un domaine custom avec TLS via Cloudflare, exporter les traces OTEL vers Cloud Trace, et solder la dette technique Phase B.

**Architecture:** GitHub Actions + Workload Identity Federation (zéro clé JSON dans secrets) pour build/push image + apply Terraform + run migration job. Cloudflare en proxy DNS devant des Cloud Run domain mappings (TLS auto Google-managed). OTLP gRPC export vers Cloud Trace via WIF côté Cloud Run. Module Terraform étendu, pas de duplication d'env (single `dev` qui fait office de prod — un seul cluster GCP).

**Tech Stack:** Workload Identity Federation, GitHub Actions, Cloudflare provider Terraform, Cloud Run domain mappings, OpenTelemetry OTLP exporter, Google Cloud Trace.

**Reference spec:** `~/Work/webhook-inspector/docs/specs/2026-05-11-webhook-inspector-design.md`

**Decisions structurantes (verrouillées avant le plan) :**

| Décision | Choix | Pourquoi |
|----------|-------|----------|
| Env strategy | UN seul env (`dev`) qui sert de prod aussi | Side-project, pas de besoin staging. Ajouter un `prod` séparé = Phase D si besoin. |
| Auth GH → GCP | Workload Identity Federation | Pas de clé JSON longue durée. Best practice 2024+. |
| Trigger deploy | `push: main` | Pas de PR auto-deploy. CI test + merge → deploy. |
| Migrations | Cloud Run Job dédié `migrator`, invoqué dans le workflow avant le deploy | Évite la migration au boot du container (race condition possible avec multi-instances). |
| Image tagging | Git short SHA + `latest` | Immutabilité du SHA, latest pour rollback "current". |
| Domain provider | Au choix du user (Namecheap/Porkbun/etc.) | ~10€/an. Doit être achetable et avec API/DNS modifiables. |
| DNS provider | Cloudflare (free tier) | TLS auto, DDoS L3/L4 gratuit, analytics, cache. |
| TLS | Cloud Run domain mapping (Google-managed certs) | Cloudflare en "Full (strict)" mode. Auto-renewal. |
| OTLP destination | Cloud Trace via `otlp.googleapis.com` | Native GCP, gratuit jusqu'à 2.5M spans/mois. |
| OTEL processor | `BatchSpanProcessor` en prod (revient au défaut) | Sync exporter `SimpleSpanProcessor` était Phase A workaround pour pytest. |

**Phase C scope :**
- Block 1 : Workload Identity Federation
- Block 2 : Cloud Run Migrator Job
- Block 3 : GitHub Actions deploy workflow
- Block 4 : Domain + Cloudflare DNS + Cloud Run mapping
- Block 5 : `hook_base_url()` fix avec domaine
- Block 6 : OTLP export vers Cloud Trace
- Block 7 : Tidy Phase B dette technique
- Block 8 : Documentation mise à jour

**Hors scope Phase C :**
- Env `prod` séparé (Phase D si besoin)
- WAF / rate limiting custom (V4 — phase produit)
- Auth utilisateur (V5)
- SLO formels + status page publique (V6)

**Estimation effort** : ~8-10h temps partiel.

---

## Vue d'ensemble post-Phase C

```
                                     ┌─────────────────────────────┐
                                     │  GitHub Actions             │
                                     │  on push: main              │
                                     │   1. lint/type/test         │
                                     │   2. build + push image     │
                                     │   3. exec migrator Job      │
                                     │   4. tofu apply (new tag)   │
                                     └──────────┬──────────────────┘
                                                │
                                  Workload Identity Federation
                                  (no JSON keys)
                                                │
                                                ▼
   ┌────────────────────────────────────────────────────────────────┐
   │                  Cloudflare DNS (proxy mode)                   │
   │      app.<domain>             hook.<domain>                    │
   └─────────────┬──────────────────────────┬───────────────────────┘
                 │                          │
                 ▼                          ▼
        ┌──────────────────┐       ┌──────────────────┐
        │ Cloud Run "app"  │       │  Cloud Run       │
        │ Custom domain    │       │  "ingestor"      │
        │ Google-managed   │       │  Custom domain   │
        │ TLS              │       │  Google-managed  │
        └────────┬─────────┘       │  TLS             │
                 │                 └────────┬─────────┘
                 │                          │
                 │ traces (OTLP gRPC)       │ traces
                 └───────────┬──────────────┘
                             ▼
                  ┌──────────────────────┐
                  │  Cloud Trace         │
                  │  + Cloud Logging     │
                  └──────────────────────┘
```

## File Structure

```
~/Work/webhook-inspector/
├── infra/terraform/
│   ├── (existing files unchanged)
│   ├── wif.tf                       # NEW — Workload Identity Pool + Provider + SA + bindings
│   ├── cloud_run_migrator.tf        # NEW — migrator Cloud Run Job
│   ├── cloudflare.tf                # NEW — Cloudflare provider + DNS records
│   ├── cloud_run_domain_mapping.tf  # NEW — domain mappings for app + ingestor
│   └── variables.tf                 # MODIFIED — add domain + cloudflare vars
├── .github/workflows/
│   ├── lint-and-test.yml            # existing, unchanged
│   └── deploy.yml                   # NEW — push:main → deploy
└── src/webhook_inspector/
    ├── config.py                    # MODIFIED — Literal type for backend, OTLP endpoint env
    ├── observability/tracing.py     # MODIFIED — switch to OTLP when env says so
    └── web/app/routes.py            # MODIFIED — hook_base_url() handles subdomain swap
```

## Workflow général

Phase C mélange opérationnel et automatisé :
- **Opérationnel** (user-driven) : Tasks 1 (achat domaine), 7 (config DNS sur le registrar)
- **Terraform** : WIF, migrator Job, Cloudflare DNS, domain mappings
- **GitHub Actions** : workflow YAML
- **Code Python** : OTLP exporter, hook_base_url fix, Literal type

---

## Block 1 : Prérequis (opérationnel)

### Task 1 : Acheter le domaine

**Pas de code. Pas de commit.**

- [ ] **Step 1.1 : Acheter un domaine**

Va sur un registrar (Namecheap, Porkbun, Cloudflare Registrar, OVH...). Achète un domaine. Coût ~10€/an pour `.io`, `.dev`, `.com`. **Note l'extension exacte** — elle apparaîtra partout dans la config DNS.

Pour la suite du plan, on utilisera `<domain>` comme placeholder. Remplace partout par ton domaine réel (ex: `qantum-inspect.io`).

- [ ] **Step 1.2 : Créer un compte Cloudflare**

Si pas déjà fait : https://dash.cloudflare.com/sign-up. Free tier suffit.

- [ ] **Step 1.3 : Ajouter le domaine à Cloudflare**

Dans le dashboard Cloudflare : `Add a site` → entre ton domaine → choisis le plan Free.

Cloudflare va scanner les DNS records existants chez ton registrar (s'il y en a). Note les **2 nameservers** Cloudflare affichés (ex: `tara.ns.cloudflare.com`, `vincent.ns.cloudflare.com`).

- [ ] **Step 1.4 : Déléguer le DNS à Cloudflare**

Va sur ton registrar → onglet DNS / Nameservers → remplace les nameservers par défaut par les 2 Cloudflare obtenus en Step 1.3.

**La propagation prend 5 min à 24h.** Pendant ce temps, Cloudflare affichera "Pending Nameserver Update" puis "Active" une fois propagé.

Vérifie :
```bash
dig +short NS <domain>
# Doit lister les 2 nameservers Cloudflare
```

- [ ] **Step 1.5 : Créer un API token Cloudflare**

Dans Cloudflare : profil → `API Tokens` → `Create Token`.

Template : "Edit zone DNS" → restreint à la zone de ton domaine. Copie le token affiché (UNE SEULE FOIS).

Stocke le token comme **secret GitHub Actions** :
```bash
gh secret set CLOUDFLARE_API_TOKEN --body "<le-token>"
```

(Si `gh` n'est pas dans le dossier webhook-inspector, ajoute `--repo quaxsze/webhook-inspector`.)

Aussi : récupère l'**ID de la zone** dans le dashboard Cloudflare (Overview → API → Zone ID, ex: `abc123def...`). Note-le, on en aura besoin.

---

## Block 2 : Workload Identity Federation

### Task 2 : WIF Pool + Provider + Deploy SA

**Files:**
- Create: `infra/terraform/wif.tf`
- Modify: `infra/terraform/variables.tf`

- [ ] **Step 2.1 : Ajouter la variable GitHub repo**

Append to `infra/terraform/variables.tf`:

```hcl
variable "github_repo" {
  type        = string
  default     = "quaxsze/webhook-inspector"
  description = "GitHub repo allowed to deploy via Workload Identity Federation (format: owner/repo)."
}
```

- [ ] **Step 2.2 : Créer `wif.tf`**

Create `infra/terraform/wif.tf`:

```hcl
# Workload Identity Pool — represents external trust boundary
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions Pool"
  description               = "Identity pool for GitHub Actions deploys"
}

# Provider — trusts GitHub OIDC tokens
resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Only allow tokens from our specific repo
  attribute_condition = "assertion.repository == \"${var.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Deploy SA — what GitHub Actions impersonates
resource "google_service_account" "deployer" {
  account_id   = "${local.name_prefix}-deployer"
  display_name = "Webhook Inspector — GitHub Actions Deployer"
  description  = "SA assumed by GitHub Actions via WIF to deploy infra and services."
}

# Allow the WIF identity to impersonate the deployer SA
resource "google_service_account_iam_member" "wif_binding" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# Grant the deployer SA the roles it needs to deploy
locals {
  deployer_project_roles = [
    "roles/run.admin",                         # deploy/update Cloud Run services + jobs
    "roles/artifactregistry.writer",           # push images
    "roles/secretmanager.secretAccessor",      # read DATABASE_URL during deploy validations
    "roles/cloudsql.client",                   # connect via Auth Proxy for migrations
    "roles/iam.serviceAccountUser",            # actAs the runtime SAs (assigned to Cloud Run)
    "roles/storage.admin",                     # tofu state bucket access (read/write)
  ]
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset(local.deployer_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Output WIF provider name (needed for GitHub Actions)
output "wif_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Workload Identity Provider name for GitHub Actions auth."
}

output "deployer_sa_email" {
  value       = google_service_account.deployer.email
  description = "Email of the SA that GitHub Actions impersonates."
}
```

- [ ] **Step 2.3 : Apply**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu plan -out=plan.out
# Should show ~9 resources to add
tofu apply plan.out
```

- [ ] **Step 2.4 : Récupérer les outputs**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
WIF_PROVIDER=$(tofu output -raw wif_provider)
DEPLOYER_SA=$(tofu output -raw deployer_sa_email)
echo "WIF_PROVIDER=$WIF_PROVIDER"
echo "DEPLOYER_SA=$DEPLOYER_SA"
```

**Stocke ces deux valeurs en variables GitHub Actions** :

```bash
cd ~/Work/webhook-inspector
gh variable set GCP_WIF_PROVIDER --body "$WIF_PROVIDER"
gh variable set GCP_DEPLOYER_SA --body "$DEPLOYER_SA"
gh variable set GCP_PROJECT_ID --body "webhook-inspector-stan-dev"
gh variable set GCP_REGION --body "europe-west1"
```

(Variables, pas secrets — ce sont des identifiants publics, pas des credentials.)

- [ ] **Step 2.5 : Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add infra/terraform/wif.tf infra/terraform/variables.tf
git commit -m "feat(infra): add Workload Identity Federation for GitHub Actions deploys"
```

---

## Block 3 : Cloud Run Migrator Job

### Task 3 : Migrator Job

**Files:**
- Create: `infra/terraform/cloud_run_migrator.tf`
- Create: `src/webhook_inspector/jobs/migrator.py`

Un Job dédié qui lance `alembic upgrade head`. Le workflow CI/CD l'invoque avant le déploiement.

- [ ] **Step 3.1 : Entrypoint Python**

Create `src/webhook_inspector/jobs/migrator.py`:

```python
"""Run Alembic migrations to head. Entrypoint for Cloud Run Job."""

import logging
import subprocess
import sys

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-migrator")
    configure_tracing(
        settings.service_name + "-migrator",
        settings.environment,
        otlp_endpoint=None,  # console exporter in jobs (short-lived)
    )

    logger.info("starting migration")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        check=False,
        capture_output=True,
        text=True,
    )

    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)

    if result.returncode != 0:
        logger.error("migration_failed", extra={"returncode": result.returncode})
        sys.exit(result.returncode)

    logger.info("migration_complete")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3.2 : Terraform Job**

Create `infra/terraform/cloud_run_migrator.tf`:

```hcl
# Reuse cleaner SA — same DB access pattern (read schema + write migrations).
# Note: alembic_version requires INSERT, so the SA needs cloudsql.client.

resource "google_cloud_run_v2_job" "migrator" {
  name     = "${local.name_prefix}-migrator"
  location = var.region

  template {
    template {
      service_account = google_service_account.cleaner.email

      max_retries = 1
      timeout     = "300s"

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_name}/webhook-inspector:${var.image_tag}"

        command = ["python"]
        args    = ["-m", "webhook_inspector.jobs.migrator"]

        resources {
          limits = {
            cpu    = "1000m"
            memory = "512Mi"
          }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "ENVIRONMENT"
          value = var.environment
        }
        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.cloudsql_client,
    google_secret_manager_secret_iam_member.database_url_cleaner,
  ]
}

# Allow deployer SA to invoke the migrator job
resource "google_cloud_run_v2_job_iam_member" "migrator_deployer_invoker" {
  location = google_cloud_run_v2_job.migrator.location
  name     = google_cloud_run_v2_job.migrator.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}
```

- [ ] **Step 3.3 : Apply**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu plan -out=plan.out
tofu apply plan.out
```

- [ ] **Step 3.4 : Test manuel (rebuild image d'abord)**

Le job référence `image_tag = var.image_tag` qui est l'image existante en AR. Le migrator est inclus dans l'image (le Dockerfile copie tout `src/`). Vérifie :

```bash
gcloud run jobs execute webhook-inspector-migrator --region=europe-west1 --wait
```

Sortie attendue : `Succeeded` (la migration `0001_initial` est déjà appliquée → no-op `INFO [alembic.runtime.migration] Will not autogenerate a migration.`).

Logs :
```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=webhook-inspector-migrator' --limit=10 --format="value(textPayload, jsonPayload.event)" --order=desc
```

Doit afficher `migration_complete`.

- [ ] **Step 3.5 : Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add infra/terraform/cloud_run_migrator.tf src/webhook_inspector/jobs/migrator.py
git commit -m "feat(jobs): add migrator Cloud Run Job for CI migrations"
```

---

## Block 4 : GitHub Actions deploy workflow

### Task 4 : Deploy workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 4.1 : Workflow**

Create `.github/workflows/deploy.yml`:

```yaml
name: deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  id-token: write  # required for WIF

env:
  GCP_PROJECT_ID: ${{ vars.GCP_PROJECT_ID }}
  GCP_REGION: ${{ vars.GCP_REGION }}
  ARTIFACT_REPO: webhook-inspector
  IMAGE_NAME: webhook-inspector

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - uses: actions/checkout@v4

      - name: Set image tag
        id: tag
        run: echo "tag=$(git rev-parse --short HEAD)" >> "$GITHUB_OUTPUT"

      - name: Authenticate to GCP via WIF
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_DEPLOYER_SA }}

      - name: Set up gcloud
        uses: google-github-actions/setup-gcloud@v2

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker ${{ env.GCP_REGION }}-docker.pkg.dev --quiet

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push image
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: true
          tags: |
            ${{ env.GCP_REGION }}-docker.pkg.dev/${{ env.GCP_PROJECT_ID }}/${{ env.ARTIFACT_REPO }}/${{ env.IMAGE_NAME }}:${{ steps.tag.outputs.tag }}
            ${{ env.GCP_REGION }}-docker.pkg.dev/${{ env.GCP_PROJECT_ID }}/${{ env.ARTIFACT_REPO }}/${{ env.IMAGE_NAME }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Update migrator Job image
        run: |
          gcloud run jobs update webhook-inspector-migrator \
            --image=${{ env.GCP_REGION }}-docker.pkg.dev/${{ env.GCP_PROJECT_ID }}/${{ env.ARTIFACT_REPO }}/${{ env.IMAGE_NAME }}:${{ steps.tag.outputs.tag }} \
            --region=${{ env.GCP_REGION }}

      - name: Execute migrations
        run: |
          gcloud run jobs execute webhook-inspector-migrator \
            --region=${{ env.GCP_REGION }} \
            --wait

      - name: Set up OpenTofu
        uses: opentofu/setup-opentofu@v1
        with:
          tofu_version: 1.11.7

      - name: Terraform apply (update image_tag)
        working-directory: infra/terraform
        env:
          TF_VAR_project_id: ${{ env.GCP_PROJECT_ID }}
          TF_VAR_image_tag: ${{ steps.tag.outputs.tag }}
        run: |
          tofu init -backend-config="bucket=${{ env.GCP_PROJECT_ID }}-tfstate"
          tofu apply -auto-approve -target=google_cloud_run_v2_service.ingestor -target=google_cloud_run_v2_service.app -target=google_cloud_run_v2_job.cleaner -target=google_cloud_run_v2_job.migrator

      - name: Smoke test deployed services
        run: |
          APP_URL=$(gcloud run services describe webhook-inspector-app --region=${{ env.GCP_REGION }} --format='value(status.url)')
          INGESTOR_URL=$(gcloud run services describe webhook-inspector-ingestor --region=${{ env.GCP_REGION }} --format='value(status.url)')

          # Service should respond
          test "$(curl -sI ${APP_URL}/ | head -1 | tr -d '\r' | awk '{print $2}')" = "404"
          test "$(curl -sI ${INGESTOR_URL}/ | head -1 | tr -d '\r' | awk '{print $2}')" = "404"

          # Full flow
          TOKEN=$(curl -sX POST ${APP_URL}/api/endpoints | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
          STATUS=$(curl -sX POST ${INGESTOR_URL}/h/${TOKEN} -d 'ci-deploy-smoke' -o /dev/null -w '%{http_code}')
          test "$STATUS" = "200" || { echo "smoke test failed with status $STATUS"; exit 1; }

          echo "Deploy successful. App: $APP_URL"
```

**Notes critiques :**
- `id-token: write` est requis pour que GitHub émette un OIDC token vers GCP.
- Le `Terraform apply` est ciblé (`-target=...`) sur les ressources Cloud Run uniquement — évite un drift apply complet à chaque push (qui pourrait recreer le pool WIF inutilement).
- L'option `--auto-approve` est OK en CI (le diff a été reviewé en PR via tofu plan local).
- Le migrator est mis à jour AVANT son exécution pour utiliser la nouvelle image (sinon il tournerait sur l'ancienne).

- [ ] **Step 4.2 : Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add .github/workflows/deploy.yml
git commit -m "ci: add deploy workflow with WIF + build/push/migrate/apply/smoke"
```

- [ ] **Step 4.3 : Test du workflow**

Pousse une PR vide pour déclencher (modifie un fichier mineur, par ex. README).

```bash
echo "" >> README.md
git add README.md
git commit -m "test: trigger first auto-deploy"
git push origin feat/v1-phase-c
```

**Le workflow tournera après le merge dans main.** Pour tester sans merge, déclenche manuellement :

```bash
gh workflow run deploy.yml --ref feat/v1-phase-c
gh run watch
```

Verifie : auth WIF OK, build push OK, migrator OK, tofu apply OK, smoke OK.

**Si auth WIF échoue** ("failed to generate Google Cloud federated token"):
- Vérifie `attribute_condition` dans `wif.tf` (doit matcher exactement `quaxsze/webhook-inspector`)
- Vérifie le `principalSet` dans `google_service_account_iam_member.wif_binding`
- Vérifie les variables GitHub (`gh variable list`)

---

## Block 5 : Domaine + Cloudflare + Cloud Run domain mapping

### Task 5 : Variables + Cloudflare provider

**Files:**
- Modify: `infra/terraform/variables.tf`, `versions.tf`

- [ ] **Step 5.1 : Variables**

Append to `infra/terraform/variables.tf`:

```hcl
variable "domain" {
  type        = string
  default     = ""
  description = "Apex domain (e.g. 'example.com'). Cloud Run is mapped to app.<domain> and hook.<domain>. Empty string disables domain mapping (used in CI deploys that don't touch DNS)."
}

variable "cloudflare_api_token" {
  type        = string
  default     = ""
  description = "Cloudflare API token with Zone DNS edit rights. Provided via TF_VAR_cloudflare_api_token. Empty for CI runs that don't touch Cloudflare resources."
  sensitive   = true
}

variable "cloudflare_zone_id" {
  type        = string
  default     = ""
  description = "Cloudflare Zone ID of the domain (from the dashboard Overview page). Empty for CI runs."
}
```

- [ ] **Step 5.2 : Cloudflare provider**

In `infra/terraform/versions.tf`, add to `required_providers`:

```hcl
cloudflare = {
  source  = "cloudflare/cloudflare"
  version = "~> 4.40"
}
```

After the existing `provider "google"` block, add:

```hcl
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
```

- [ ] **Step 5.3 : Update terraform.tfvars locally**

Append to `infra/terraform/terraform.tfvars` (gitignored):

```hcl
domain             = "<your-domain>"
cloudflare_zone_id = "<your-zone-id>"
# cloudflare_api_token is passed via TF_VAR_cloudflare_api_token env var (not in tfvars)
```

Export the token for local tofu runs:
```bash
export TF_VAR_cloudflare_api_token="<your-token>"
```

- [ ] **Step 5.4 : `tofu init -upgrade`**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu init -upgrade
```

Should pull the cloudflare provider.

- [ ] **Step 5.5 : Commit**

```bash
git add infra/terraform/variables.tf infra/terraform/versions.tf
git commit -m "feat(infra): add Cloudflare provider and domain variables"
```

### Task 6 : Cloud Run domain mapping

**Files:**
- Create: `infra/terraform/cloud_run_domain_mapping.tf`

- [ ] **Step 6.1 : Domain mapping**

Create `infra/terraform/cloud_run_domain_mapping.tf`:

```hcl
# Note: Cloud Run domain mappings require the domain to be verified
# in GCP. The simplest path is to use Cloud Run's "*.run.app" mechanism,
# but for custom domains we need the apex zone delegated to Cloudflare,
# and then we create CNAMEs that point to Cloud Run's ghs.googlehosted.com.
#
# Domain verification: GCP does NOT require explicit verification when
# you use the `google_cloud_run_domain_mapping` resource with a verified
# domain. To verify, run once manually:
#   gcloud domains verify <domain>
# This opens a browser, you complete the verification, GCP records the
# domain as verified for your user. After that, this terraform resource
# can claim the domain for the Cloud Run services.

resource "google_cloud_run_domain_mapping" "app" {
  location = var.region
  name     = "app.${var.domain}"

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.app.name
  }
}

resource "google_cloud_run_domain_mapping" "ingestor" {
  location = var.region
  name     = "hook.${var.domain}"

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.ingestor.name
  }
}

# Cloudflare DNS records pointing to Cloud Run
resource "cloudflare_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = "app"
  value   = "ghs.googlehosted.com"
  type    = "CNAME"
  proxied = true   # Cloudflare proxy (orange cloud) — TLS + DDoS
  ttl     = 1      # 1 = Automatic when proxied

  depends_on = [google_cloud_run_domain_mapping.app]
}

resource "cloudflare_record" "hook" {
  zone_id = var.cloudflare_zone_id
  name    = "hook"
  value   = "ghs.googlehosted.com"
  type    = "CNAME"
  proxied = true
  ttl     = 1

  depends_on = [google_cloud_run_domain_mapping.ingestor]
}

output "app_custom_url" {
  value = "https://app.${var.domain}"
}

output "ingestor_custom_url" {
  value = "https://hook.${var.domain}"
}
```

- [ ] **Step 6.2 : Vérifier le domaine dans GCP**

Avant l'apply, vérifie le domaine (one-shot, manuel) :

```bash
gcloud domains verify <your-domain>
```

Ça ouvre un navigateur. Tu copies une chaîne TXT dans Cloudflare DNS (manuel ou via Cloudflare API), tu valides. Une fois validé, ton compte Google a le domaine vérifié et peut le mapper aux Cloud Run services.

**Important** : la vérification est sur ton COMPTE Google, pas sur le projet GCP. Si tu changes de projet GCP, pas besoin de re-vérifier.

- [ ] **Step 6.3 : Apply**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu plan -out=plan.out
tofu apply plan.out
```

Plan attendu : 4 ressources (2 domain mappings + 2 CNAMEs).

- [ ] **Step 6.4 : Attendre TLS provisioning**

Google-managed certs prennent **5-30 minutes** à être provisionnés et validés. Vérifie :

```bash
gcloud beta run domain-mappings list --region=europe-west1 --format="table(metadata.name,status.conditions[0].type,status.conditions[0].status)"
```

Tu dois voir `CertificateProvisioned: True` et `Ready: True` pour les deux mappings.

- [ ] **Step 6.5 : Test**

```bash
curl -sI https://app.<your-domain>/ | head -2
# HTTP/2 404
# server: Google Frontend

curl -sI https://hook.<your-domain>/ | head -2
# Idem

# Smoke E2E sur le vrai domaine
TOKEN=$(curl -sX POST https://app.<your-domain>/api/endpoints | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -sX POST -d 'test' https://hook.<your-domain>/h/${TOKEN}
curl -s https://app.<your-domain>/api/endpoints/${TOKEN}/requests | python3 -m json.tool
```

- [ ] **Step 6.6 : Commit**

```bash
git add infra/terraform/cloud_run_domain_mapping.tf
git commit -m "feat(infra): map app.<domain> + hook.<domain> to Cloud Run via Cloudflare DNS"
```

---

## Block 6 : Fix `hook_base_url()` avec subdomain

### Task 7 : hook_base_url fix

**Files:**
- Modify: `src/webhook_inspector/web/app/routes.py`
- Modify: `tests/integration/web/test_app_create_endpoint.py`

Le helper existe déjà avec une logique partielle. On la rend plus robuste.

- [ ] **Step 7.1 : Test failing**

Le test actuel ne vérifie pas le swap `app.` → `hook.`. Ajoute un test dédié.

Append to `tests/integration/web/test_app_create_endpoint.py`:

```python
import pytest


@pytest.mark.parametrize("base_url, expected_hook_prefix", [
    ("https://app.example.com", "https://hook.example.com/h/"),
    ("https://webhook-inspector-app-xxx.a.run.app", "https://webhook-inspector-ingestor-xxx.a.run.app/h/"),
    ("http://localhost:8000", "http://localhost:8001/h/"),
])
async def test_hook_base_url_swaps_subdomain(
    monkeypatch, database_url, engine, base_url, expected_hook_prefix
):
    monkeypatch.setenv("DATABASE_URL", database_url.replace("+psycopg_async", "+psycopg"))
    from webhook_inspector.web.app import deps
    deps.get_settings.cache_clear()
    deps._engine.cache_clear()
    deps._session_factory.cache_clear()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.post("/api/endpoints")
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"].startswith(expected_hook_prefix), \
            f"Expected URL starting with {expected_hook_prefix}, got {data['url']}"
```

Note: also need `from httpx import ASGITransport` and `from webhook_inspector.web.app.main import app` at the top (they're already imported in the existing test file).

- [ ] **Step 7.2 : Run test, see one failure**

```bash
cd /Users/stan/Work/webhook-inspector
uv run pytest tests/integration/web/test_app_create_endpoint.py::test_hook_base_url_swaps_subdomain -v
```

Expected: the `*-app-xxx.a.run.app` case fails (the current helper doesn't handle this pattern correctly).

- [ ] **Step 7.3 : Fix `hook_base_url` in routes.py**

Edit `src/webhook_inspector/web/app/routes.py`. Find `hook_base_url`:

```python
def hook_base_url(request: Request) -> str:
    """Derive the ingestor base URL from the app base URL.

    Prod: app.<domain>  →  hook.<domain>
    Local docker-compose: localhost:8000 → localhost:8001
    """
    base = str(request.base_url).rstrip("/")
    if "://app." in base:
        return base.replace("://app.", "://hook.")
    if ":8000" in base:
        return base.replace(":8000", ":8001")
    return base  # fallback (single-host dev)
```

Replace with a more comprehensive version:

```python
import re


def hook_base_url(request: Request) -> str:
    """Derive the ingestor base URL from the app base URL.

    Cases handled (in priority order):
    1. Prod subdomain:    https://app.<domain>          → https://hook.<domain>
    2. Cloud Run default: https://*-app-*.a.run.app     → https://*-ingestor-*.a.run.app
    3. Local compose:     http://localhost:8000         → http://localhost:8001
    4. Fallback:          unchanged (single-host dev)
    """
    base = str(request.base_url).rstrip("/")

    # Case 1: subdomain swap
    if "://app." in base:
        return base.replace("://app.", "://hook.")

    # Case 2: Cloud Run auto-generated hostname (e.g. webhook-inspector-app-4e7krtbaca-ew.a.run.app)
    cloud_run_match = re.search(r"webhook-inspector-app(-[a-z0-9]+)?-([a-z0-9]+)\.a\.run\.app", base)
    if cloud_run_match:
        return base.replace("webhook-inspector-app", "webhook-inspector-ingestor")

    # Case 3: local dev port swap
    if ":8000" in base:
        return base.replace(":8000", ":8001")

    # Case 4: fallback (single-host, e.g. http://test/)
    return base
```

Add the `import re` at the top of the file if not present.

- [ ] **Step 7.4 : Run test, confirm PASS**

```bash
uv run pytest tests/integration/web/test_app_create_endpoint.py -v
```

All tests pass.

- [ ] **Step 7.5 : Smoke test on live deployment**

After the next deploy (push to main triggers CI), verify:

```bash
curl -sX POST https://app.<your-domain>/api/endpoints | jq .url
# Should print "https://hook.<your-domain>/h/..."
```

The URL is now directly usable as a webhook target. ✓

- [ ] **Step 7.6 : Commit**

```bash
git add src/webhook_inspector/web/app/routes.py tests/integration/web/test_app_create_endpoint.py
git commit -m "fix(web): hook_base_url handles Cloud Run + subdomain + localhost"
```

---

## Block 7 : Cloud Trace export

### Task 8 : Cloud Trace exporter (Python)

**Files:**
- Modify: `pyproject.toml` (new dep: `opentelemetry-exporter-gcp-trace`)
- Modify: `src/webhook_inspector/config.py`
- Modify: `src/webhook_inspector/observability/tracing.py`

**Why Cloud Trace exporter, not OTLP**: pure OTLP gRPC to `telemetry.googleapis.com` requires manual ADC auth headers and metadata. The `opentelemetry-exporter-gcp-trace` library is purpose-built for Cloud Trace: it uses ADC automatically, handles authentication, and just works inside Cloud Run.

- [ ] **Step 8.1 : Add dep**

```bash
cd /Users/stan/Work/webhook-inspector
uv add opentelemetry-exporter-gcp-trace
```

- [ ] **Step 8.2 : Settings extension**

Edit `src/webhook_inspector/config.py`. Add the `cloud_trace_enabled` field:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    cloud_trace_enabled: bool = False  # True in prod (Cloud Run env), False in local/test
```

- [ ] **Step 8.3 : Tracing module — switch processor based on flag**

Edit `src/webhook_inspector/observability/tracing.py`. Replace top imports and `configure_tracing`:

```python
from collections.abc import Callable

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from sqlalchemy.ext.asyncio import AsyncEngine


def configure_tracing(
    service_name: str, environment: str, cloud_trace_enabled: bool = False
) -> None:
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)

    if cloud_trace_enabled:
        # Production: batch export to Cloud Trace via GCP exporter (uses ADC).
        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
    else:
        # Local/test: synchronous console export, no daemon thread.
        # Avoids 'I/O operation on closed file' at pytest exit.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def instrument_app(app: FastAPI, engine: AsyncEngine | None = None) -> None:
    FastAPIInstrumentor.instrument_app(app)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
```

(Remove the unused `from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter` import.)

- [ ] **Step 8.4 : Wire lifespan handlers to pass the flag**

Edit `src/webhook_inspector/web/app/main.py`. In `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-app")
    configure_tracing(
        settings.service_name + "-app",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )
    instrument_app(app, _engine())
    yield
```

Same in `src/webhook_inspector/web/ingestor/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-ingestor")
    configure_tracing(
        settings.service_name + "-ingestor",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )
    instrument_app(app, _engine())
    yield
```

In `src/webhook_inspector/jobs/cleaner.py`:

```python
def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-cleaner")
    configure_tracing(
        settings.service_name + "-cleaner",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )
    # ... existing code ...
```

And in `src/webhook_inspector/jobs/migrator.py` (from Task 3.1):

```python
def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-migrator")
    configure_tracing(
        settings.service_name + "-migrator",
        settings.environment,
        cloud_trace_enabled=settings.cloud_trace_enabled,
    )
    # ... existing code ...
```

- [ ] **Step 8.5 : Tests still pass (CLOUD_TRACE_ENABLED unset → False)**

```bash
cd /Users/stan/Work/webhook-inspector
uv run pytest tests/ -v
uv run ruff check src tests
uv run mypy src
```

All 51 tests pass.

- [ ] **Step 8.6 : Commit**

```bash
git add pyproject.toml uv.lock src/webhook_inspector/config.py src/webhook_inspector/observability/tracing.py src/webhook_inspector/web/app/main.py src/webhook_inspector/web/ingestor/main.py src/webhook_inspector/jobs/cleaner.py src/webhook_inspector/jobs/migrator.py
git commit -m "feat(obs): conditional Cloud Trace exporter (BatchSpanProcessor in prod, console in dev)"
```

### Task 9 : Terraform — Cloud Trace env + IAM

**Files:**
- Modify: `infra/terraform/cloud_run_ingestor.tf`, `cloud_run_app.tf`, `cloud_run_cleaner.tf`, `cloud_run_migrator.tf`, `service_accounts.tf`, `apis.tf`

- [ ] **Step 9.1 : Add CLOUD_TRACE_ENABLED env var to each service**

In each of the 4 `cloud_run_*.tf` files, add inside `containers { env { ... } }` section:

```hcl
env {
  name  = "CLOUD_TRACE_ENABLED"
  value = "true"
}
```

(Place it alongside the existing env vars.)

- [ ] **Step 9.2 : Grant `roles/cloudtrace.agent` to runtime SAs**

Append to `infra/terraform/service_accounts.tf`:

```hcl
# Cloud Trace write access for runtime SAs
locals {
  trace_writer_sas = [
    google_service_account.ingestor.email,
    google_service_account.app.email,
    google_service_account.cleaner.email,
  ]
}

resource "google_project_iam_member" "trace_writer" {
  for_each = toset(local.trace_writer_sas)

  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${each.value}"
}
```

- [ ] **Step 9.3 : Enable Cloud Trace API**

Add to `infra/terraform/apis.tf`:

```hcl
# in the required_apis local list, append:
"cloudtrace.googleapis.com",
```

- [ ] **Step 9.4 : Apply**

```bash
cd /Users/stan/Work/webhook-inspector/infra/terraform
tofu plan -out=plan.out
tofu apply plan.out
```

Plan attendu : ~7 changes (3 IAM + 1 API + 3 Cloud Run env additions).

- [ ] **Step 9.5 : Test**

Hit the app to generate traces:
```bash
curl -sX POST https://app.<your-domain>/api/endpoints
TOKEN=$(curl -sX POST https://app.<your-domain>/api/endpoints | jq -r .token)
curl -sX POST -d 'trace-test' https://hook.<your-domain>/h/${TOKEN}
```

Wait ~30s, then check Cloud Trace:
```bash
gcloud trace traces list --limit=5 --format="table(traceId, spans[0].name)"
```

Or open Cloud Console → Trace → Trace Explorer. You should see spans for FastAPI requests and SQLAlchemy queries.

- [ ] **Step 9.6 : Commit**

```bash
cd /Users/stan/Work/webhook-inspector
git add infra/terraform/cloud_run_ingestor.tf infra/terraform/cloud_run_app.tf infra/terraform/cloud_run_cleaner.tf infra/terraform/cloud_run_migrator.tf infra/terraform/service_accounts.tf infra/terraform/apis.tf
git commit -m "feat(obs): export OTEL traces to Cloud Trace via OTLP"
```

---

## Block 8 : Tidy Phase B dette technique

### Task 10 : Literal type for backend

**Files:**
- Modify: `src/webhook_inspector/config.py`

- [ ] **Step 10.1 : Change `blob_storage_backend` to Literal**

Edit `config.py`. Add `from typing import Literal` import. Change the field type:

```python
blob_storage_backend: Literal["local", "gcs"] = "local"
```

Run:
```bash
cd /Users/stan/Work/webhook-inspector
uv run pytest tests/ -v
uv run mypy src
```

The factory test `test_factory_raises_on_unknown_backend` will now fail at Settings construction (pydantic rejects "redis" as not in Literal). Update the test:

In `tests/unit/test_blob_storage_factory.py`, change `test_factory_raises_on_unknown_backend`:

```python
from pydantic import ValidationError


def test_factory_raises_on_unknown_backend():
    """Pydantic itself rejects backend values not in the Literal."""
    env = {
        "BLOB_STORAGE_BACKEND": "redis",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings
        with pytest.raises(ValidationError):
            Settings()
```

Add `from pydantic import ValidationError` to the top of the test file (it's already a transitive dep of pydantic-settings).

Run tests again — all pass.

- [ ] **Step 10.2 : Commit**

```bash
git add src/webhook_inspector/config.py tests/unit/test_blob_storage_factory.py
git commit -m "refactor(config): use Literal type for blob_storage_backend (Pydantic validation at boot)"
```

### Task 11 : Missing factory GCS happy path test

**Files:**
- Modify: `tests/unit/test_blob_storage_factory.py`

- [ ] **Step 11.1 : Add test**

Append to `tests/unit/test_blob_storage_factory.py`:

```python
from unittest.mock import MagicMock


def test_factory_returns_gcs_when_backend_is_gcs_with_bucket():
    """The happy path for GCS backend instantiates GcsBlobStorage with the bucket."""
    env = {
        "BLOB_STORAGE_BACKEND": "gcs",
        "GCS_BUCKET_NAME": "test-bucket-name",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings
        from webhook_inspector.infrastructure.storage.gcs_blob_storage import GcsBlobStorage

        # Patch the google client to avoid real ADC lookup
        with patch("google.cloud.storage.Client") as mock_client:
            mock_client.return_value = MagicMock()
            settings = Settings()
            storage = _import_factory().make_blob_storage(settings)
            assert isinstance(storage, GcsBlobStorage)
```

- [ ] **Step 11.2 : Run + commit**

```bash
uv run pytest tests/unit/test_blob_storage_factory.py -v
# 4 passed (3 existing + 1 new)
git add tests/unit/test_blob_storage_factory.py
git commit -m "test(factory): cover GCS happy path with mocked storage.Client"
```

### Task 12 : Dockerfile non-root user

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 12.1 : Add non-root user**

Edit `Dockerfile`. In the runtime stage (`FROM python:3.13-slim AS runtime`), after the `COPY --from=builder /app /app` line, add:

```dockerfile
# Run as non-root user
RUN groupadd -r appuser && useradd -r -u 1001 -g appuser appuser \
    && chown -R appuser:appuser /app
USER appuser
```

- [ ] **Step 12.2 : Local build verification**

```bash
cd /Users/stan/Work/webhook-inspector
docker build -t webhook-inspector:noroot .
docker run --rm webhook-inspector:noroot whoami
# Should print: appuser
```

- [ ] **Step 12.3 : Commit**

```bash
git add Dockerfile
git commit -m "fix(docker): run container as non-root (appuser uid 1001)"
```

Next deploy via CI will rebuild + push + apply the new image.

### Task 13 : Robust pg_isready polling in run_migration.sh

**Files:**
- Modify: `scripts/run_migration.sh`

- [ ] **Step 13.1 : Replace sleep with pg_isready**

Edit `scripts/run_migration.sh`. Find:

```bash
# Wait for proxy ready
sleep 3
```

Replace with:

```bash
# Wait for proxy ready
echo "==> Waiting for cloud-sql-proxy to be ready..."
for _ in $(seq 1 30); do
  if pg_isready -h localhost -p "$LOCAL_PORT" -U "$DB_USER" >/dev/null 2>&1; then
    echo "    Proxy ready"
    break
  fi
  sleep 0.5
done
```

- [ ] **Step 13.2 : Test (re-run migration)**

```bash
cd /Users/stan/Work/webhook-inspector
./scripts/run_migration.sh webhook-inspector-stan-dev
```

Should still succeed (idempotent). Faster on a warm system.

- [ ] **Step 13.3 : Commit**

```bash
git add scripts/run_migration.sh
git commit -m "fix(scripts): replace sleep with pg_isready polling in migration script"
```

---

## Block 9 : Documentation

### Task 14 : Update README

**Files:**
- Modify: `infra/terraform/README.md`
- Modify: `README.md`

- [ ] **Step 14.1 : infra README**

Edit `infra/terraform/README.md` — add a new section "Continuous Deployment" before "Tearing down":

```markdown
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

**No GitHub secrets needed** — auth is via Workload Identity Federation.

**Required Cloudflare secret:**
- `CLOUDFLARE_API_TOKEN` (gh secret) — only used if you ever run Terraform via CI (not in current deploy workflow, which targets only Cloud Run resources).

## Custom Domain Setup

Production URLs:
- App: `https://app.<your-domain>`
- Ingestor: `https://hook.<your-domain>`

To re-do the DNS setup (Phase C Block 5):
1. Buy a domain
2. Delegate DNS to Cloudflare
3. Set `TF_VAR_cloudflare_api_token` env var locally
4. Add `domain` + `cloudflare_zone_id` to `terraform.tfvars`
5. `gcloud domains verify <domain>` once (manual)
6. `tofu apply` — creates Cloud Run domain mappings + Cloudflare CNAMEs
7. Wait 5-30 min for Google-managed TLS certs
```

- [ ] **Step 14.2 : Main README**

Edit `README.md`. Update the Quickstart section to mention production:

```markdown
## Production deployment

Live URLs (when configured):
- App: `https://app.<your-domain>`
- Ingestor (webhook target): `https://hook.<your-domain>`

Generated webhook URLs (`POST /api/endpoints`) automatically point to the ingestor subdomain. Use as-is in any service that sends webhooks (Stripe, GitHub, Slack...).

Deploys are automatic on push to `main`. See `infra/terraform/README.md` for the deployment pipeline.
```

- [ ] **Step 14.3 : Commit**

```bash
git add infra/terraform/README.md README.md
git commit -m "docs: document Phase C — continuous deployment + custom domain"
```

---

## Self-review

(Run after writing the plan — fix inline.)

**1. Spec coverage**

| Spec requirement | Task |
|------------------|------|
| GitHub Actions deploy auto on push main | Task 4 ✓ |
| Workload Identity Federation (no JSON keys) | Tasks 2, 4 ✓ |
| Migration in CI before deploy | Tasks 3, 4 (migrator Job) ✓ |
| Custom domain + DNS Cloudflare | Tasks 5, 6 ✓ |
| TLS Cloud Run domain mapping | Task 6 ✓ |
| Fix hook_base_url bug | Task 7 ✓ |
| OTLP export Cloud Trace | Tasks 8, 9 ✓ |
| structlog logs → Cloud Logging | Already in Phase A via stdout JSON → auto-ingested by Cloud Logging |
| Health monitoring | Out of scope — Phase D or V6 |
| Tidy Phase B dette : Literal type, factory GCS test, non-root Docker, pg_isready | Tasks 10, 11, 12, 13 ✓ |
| Doc updates | Task 14 ✓ |

**2. Type consistency**

- `otlp_endpoint: str | None` in Settings — consistent in `configure_tracing(..., otlp_endpoint=)`.
- `blob_storage_backend: Literal["local", "gcs"]` — only the 2 strings the factory handles. Consistent.
- `hook_base_url(request: Request) -> str` — signature unchanged, only internal logic extended.

**3. Pas de placeholder détecté** sauf `<domain>` qui est intentionnel (le user fournit son domaine).

---

## Next Steps (post-Phase C)

Une fois Phase C livrée :
- **Phase D (optionnel)** : env `prod` séparé via workspaces Terraform, blue/green deploy avec traffic splitting.
- **V2 produit** : custom response + replay, métriques OTEL custom + dashboards Cloud Monitoring + alerting policies.
- **V4 produit** : rate limiting + WAF Cloudflare + Memorystore Redis.
- **V6 produit** : SLO formels + status page publique.
