# Webhook Inspector V1 — Phase B : Infrastructure GCP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** déployer manuellement la stack webhook-inspector sur GCP via `gcloud run deploy`, avec toutes les ressources (Cloud SQL, GCS, Cloud Run × 2 + Job, Cloud Scheduler, Secret Manager, Artifact Registry, IAM) gérées par Terraform.

**Architecture:** module Terraform unique (`infra/terraform/`) déployant un env `dev`. État stocké dans un bucket GCS bootstrapped par script manuel one-shot. Cloud SQL connecté via Cloud SQL Auth Proxy en sidecar Cloud Run. Image Docker buildée localement + push vers Artifact Registry. Le remplacement `LocalBlobStorage` → `GcsBlobStorage` est la seule modification code de cette phase.

**Tech Stack:** Terraform 1.10+, Google Cloud Provider, gcloud CLI, Cloud Run (gen2), Cloud SQL Postgres 16, Cloud Storage, Secret Manager, Artifact Registry, Cloud Scheduler, Docker. Python code reste 3.13 / FastAPI.

**Reference spec:** `~/Work/webhook-inspector/docs/specs/2026-05-11-webhook-inspector-design.md` — section "Infrastructure V1".

**Decisions structurantes (verrouillées avant le plan) :**

| Décision | Choix | Pourquoi |
|----------|-------|----------|
| Région | `europe-west1` (St. Ghislain, BE) | Latence ~10ms depuis France, prix raisonnable. |
| Terraform state | Backend GCS distant | Bonne pratique, value pédagogique. Bootstrap manuel one-shot. |
| Cloud SQL connection | Auth Proxy sidecar dans Cloud Run | Plus simple qu'un VPC privé. Connexion sécurisée via socket Unix. |
| Cloud SQL tier | `db-f1-micro` single-zone | Side-project. Pas de HA en V1. ~9€/mois. |
| Environnements | `dev` seulement | `prod` arrive en Phase C avec la CI/CD. |
| Domaine | Pas en Phase B | Utilise les URLs `*.run.app` auto-générées. Domaine + Cloudflare arrivent en Phase C. |
| Concurrency Cloud Run | `ingestor` max=20 / `app` max=5 | Spec design doc. |
| Min instances | `ingestor` min=0 (cold starts OK) / `app` min=1 (SSE persistant) | Coût optimal pour side-project. |
| GCS lifecycle | Delete après 7 jours | Cohérent avec rétention endpoints. |
| Budget alert | €20/mois soft (notif email) | Pas de hard kill GCP — surveillance manuelle. |

**Phase B scope :**
- Création compte GCP + projet + budget
- Bootstrap Terraform state
- Module Terraform complet : Cloud SQL, GCS, Secret Manager, Artifact Registry, Cloud Run × 2 + Job, Cloud Scheduler, IAM
- Nouveau adapter `GcsBlobStorage` + injection conditionnelle
- Build/push image + run alembic migration + premier déploiement manuel
- Smoke test cloud (curl POST puis viewer)

**Hors scope Phase B :**
- CI/CD automatisée (Phase C)
- DNS / domaine / TLS Cloudflare (Phase C)
- OTLP export Cloud Trace (Phase C — Phase B garde le console exporter en stdout)
- Multi-environnements (`prod`)
- Rate limiting / WAF (Phase V4)
- Auth utilisateur (V5)

---

## Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────────────┐
│  GCP Project: webhook-inspector-<suffix>-dev                         │
│                                                                      │
│  ┌────────────────┐    ┌────────────────┐    ┌──────────────────┐   │
│  │  Cloud Run     │    │  Cloud Run     │    │  Cloud Run Job   │   │
│  │  "ingestor"    │    │  "app"         │    │  "cleaner"       │   │
│  │                │    │                │    │                  │   │
│  │  ┌──────────┐  │    │  ┌──────────┐  │    │  ┌────────────┐  │   │
│  │  │ webhook  │  │    │  │ webhook  │  │    │  │  webhook   │  │   │
│  │  │inspector │  │    │  │inspector │  │    │  │ inspector  │  │   │
│  │  │ container│  │    │  │ container│  │    │  │ (cleaner)  │  │   │
│  │  └────┬─────┘  │    │  └────┬─────┘  │    │  └─────┬──────┘  │   │
│  │       │socket  │    │       │socket  │    │        │         │   │
│  │  ┌────┴─────┐  │    │  ┌────┴─────┐  │    │  (direct conn)   │   │
│  │  │ cloudsql │  │    │  │ cloudsql │  │    │                  │   │
│  │  │  proxy   │  │    │  │  proxy   │  │    │  Triggered by    │   │
│  │  │ sidecar  │  │    │  │ sidecar  │  │    │ Cloud Scheduler  │   │
│  │  └────┬─────┘  │    │  └────┬─────┘  │    │  (cron 03:00)    │   │
│  └───────┼────────┘    └───────┼────────┘    └──────────────────┘   │
│          │                     │                                     │
│          └─────────┬───────────┘                                     │
│                    ▼                                                 │
│          ┌──────────────────┐         ┌─────────────────────┐        │
│          │   Cloud SQL      │         │  Secret Manager     │        │
│          │   Postgres 16    │         │  - DATABASE_URL     │        │
│          │   db-f1-micro    │         │  - GCS_BUCKET_NAME  │        │
│          └──────────────────┘         └─────────────────────┘        │
│                                                                      │
│  ┌──────────────────────┐    ┌──────────────────────────┐            │
│  │   GCS bucket         │    │  Artifact Registry       │            │
│  │   blobs (7d cleanup) │    │  webhook-inspector image │            │
│  └──────────────────────┘    └──────────────────────────┘            │
└──────────────────────────────────────────────────────────────────────┘
```

## File Structure (Terraform module)

```
~/Work/webhook-inspector/
├── infra/
│   └── terraform/
│       ├── README.md                  # local notes for bootstrap + apply
│       ├── versions.tf                # provider versions
│       ├── backend.tf                 # GCS backend config
│       ├── variables.tf               # input variables
│       ├── outputs.tf                 # exported values
│       ├── locals.tf                  # naming convention
│       ├── apis.tf                    # google_project_service blocks
│       ├── service_accounts.tf        # SAs + IAM
│       ├── cloudsql.tf                # Cloud SQL instance + db + user
│       ├── secret_manager.tf          # secrets
│       ├── gcs.tf                     # blob bucket
│       ├── artifact_registry.tf       # Docker repo
│       ├── cloud_run_ingestor.tf      # ingestor service
│       ├── cloud_run_app.tf           # app service
│       ├── cloud_run_cleaner.tf       # cleaner job
│       ├── cloud_scheduler.tf         # cron trigger
│       └── terraform.tfvars.example   # example variable values
├── scripts/
│   ├── bootstrap_gcp.sh               # one-shot: create state bucket + enable APIs
│   ├── build_and_push.sh              # docker build + push to Artifact Registry
│   ├── run_migration.sh               # alembic upgrade head against Cloud SQL
│   └── smoke_test_cloud.sh            # e2e check on deployed URLs
└── src/webhook_inspector/
    └── infrastructure/storage/
        ├── local_blob_storage.py      # existing
        └── gcs_blob_storage.py        # NEW — adapter for GCS
```

## Workflow général

Phase B mélange :
- **Tâches opérationnelles user-driven** (créer compte GCP, gérer le billing) — pas de code, le user fait dans le navigateur.
- **Tâches Terraform** — écrire HCL, `terraform plan`, `terraform apply`, vérifier la ressource créée.
- **Tâches code Python** — un seul adapter `GcsBlobStorage` + injection conditionnelle, TDD classique.

Pour Terraform, chaque tâche suit : **PLAN → APPLY → VERIFY → COMMIT**.

---

## Block 1 : Prérequis GCP (opérationnel, user-driven)

### Task 1 : Créer le compte GCP et activer la facturation

**Pas de code. Pas de commit. Action manuelle dans le navigateur.**

- [ ] **Step 1.1 : Créer un compte Google Cloud**

Ouvre https://console.cloud.google.com/ et connecte-toi avec ton compte Google. Si c'est la première fois, accepte les TOS.

Le compte sera créé. Tu auras 300$ de crédit free trial pendant 90 jours (pas nécessaire ici, mais sympa).

- [ ] **Step 1.2 : Créer un compte de facturation**

Navigation : ☰ → Billing → "Create Billing Account".

Renseigne ta carte de crédit. **Important** : pour un side-project, GCP a un free tier permanent — Cloud Run gratuit jusqu'à 2M requêtes/mois, Cloud SQL `db-f1-micro` gratuit dans le free trial (mais payant ~9€/mois après). Pas de mauvaises surprises tant que le budget alert est en place.

- [ ] **Step 1.3 : Créer une alerte budget**

Navigation : Billing → Budgets & alerts → Create budget.
- Name : `webhook-inspector-budget`
- Amount : `20 EUR / month`
- Threshold rules : 50%, 90%, 100%, 110% — email à ton adresse perso à chaque seuil.

Ça t'envoie un email *quand* le seuil est dépassé. GCP n'arrête PAS automatiquement la facturation — c'est à toi de réagir.

- [ ] **Step 1.4 : Créer le projet GCP**

Navigation : ☰ → IAM & Admin → Manage Resources → Create Project.
- Project name : `Webhook Inspector Dev`
- Project ID : `webhook-inspector-<suffix>-dev` (ex: `webhook-inspector-stan-dev`). **Le suffix DOIT être unique au monde**. Si pris, ajoute une année ou un nombre. **Note l'ID exact pour les étapes suivantes** — tu vas le réutiliser partout.
- Billing account : sélectionne celui créé en Step 1.2.

Attends que le projet apparaisse dans le sélecteur en haut. Sélectionne-le.

- [ ] **Step 1.5 : Installer `gcloud` CLI**

Sur macOS :
```bash
brew install --cask google-cloud-sdk
```

Vérifie :
```bash
gcloud --version
```

Tu devrais voir au minimum `Google Cloud SDK 500.x.x`.

- [ ] **Step 1.6 : Authentifier `gcloud`**

```bash
gcloud auth login
gcloud auth application-default login
```

Le premier authentifie ton compte pour `gcloud` lui-même. Le second crée un credential pour les SDKs (Terraform en a besoin).

Sélectionne le projet par défaut :
```bash
gcloud config set project webhook-inspector-<suffix>-dev
gcloud config set compute/region europe-west1
```

Vérifie :
```bash
gcloud config list
gcloud auth list
```

Tu dois voir ton email + le project ID + region.

- [ ] **Step 1.7 : Pas de commit**

Cette tâche est entièrement opérationnelle. Rien à versionner.

---

### Task 2 : Bootstrap du state bucket Terraform

**Files:**
- Create: `scripts/bootstrap_gcp.sh`

Le bucket qui stocke le state Terraform doit exister **avant** que Terraform puisse l'utiliser. On le crée manuellement via gcloud, une fois. Idempotent.

- [ ] **Step 2.1 : Écrire le script bootstrap**

Create `scripts/bootstrap_gcp.sh`:

```bash
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
```

- [ ] **Step 2.2 : Rendre le script exécutable**

```bash
chmod +x scripts/bootstrap_gcp.sh
```

- [ ] **Step 2.3 : Exécuter le script**

```bash
cd ~/Work/webhook-inspector
./scripts/bootstrap_gcp.sh webhook-inspector-<suffix>-dev
```

Sortie attendue : APIs activées (peut prendre 1-2 min), bucket `webhook-inspector-<suffix>-dev-tfstate` créé.

**Vérification** :
```bash
gcloud storage buckets list --filter="name~tfstate"
gcloud services list --enabled --filter="config.name~run OR config.name~sqladmin" --format="value(config.name)"
```

Doit lister le bucket + `run.googleapis.com` + `sqladmin.googleapis.com` + tous les autres.

- [ ] **Step 2.4 : Commit**

```bash
git add scripts/bootstrap_gcp.sh
git commit -m "chore(infra): add GCP bootstrap script for APIs and Terraform state bucket"
```

---

## Block 2 : Terraform foundation

### Task 3 : Initialiser le module Terraform

**Files:**
- Create: `infra/terraform/versions.tf`, `backend.tf`, `variables.tf`, `locals.tf`, `apis.tf`, `terraform.tfvars.example`

- [ ] **Step 3.1 : Créer le dossier infra**

```bash
mkdir -p ~/Work/webhook-inspector/infra/terraform
cd ~/Work/webhook-inspector
```

- [ ] **Step 3.2 : `versions.tf`**

Create `infra/terraform/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
```

- [ ] **Step 3.3 : `backend.tf`**

Create `infra/terraform/backend.tf`:

```hcl
terraform {
  backend "gcs" {
    # bucket is provided via `terraform init -backend-config="bucket=..."`
    prefix = "terraform/state"
  }
}
```

The bucket name comes from the bootstrap (matches `${project_id}-tfstate`). Passing via `-backend-config` keeps it out of source control (the project ID may be in tfvars but the backend block stays generic).

- [ ] **Step 3.4 : `variables.tf`**

Create `infra/terraform/variables.tf`:

```hcl
variable "project_id" {
  type        = string
  description = "GCP project ID (e.g. webhook-inspector-stan-dev)"
}

variable "region" {
  type        = string
  default     = "europe-west1"
  description = "Default region for all regional resources."
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Deployment environment label (dev/staging/prod)."
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Tag of the webhook-inspector image in Artifact Registry."
}

variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Cloud SQL instance tier."
}

variable "endpoint_ttl_days" {
  type        = number
  default     = 7
  description = "Webhook endpoint TTL in days."
}

variable "ingestor_min_instances" {
  type    = number
  default = 0
}

variable "ingestor_max_instances" {
  type    = number
  default = 20
}

variable "app_min_instances" {
  type    = number
  default = 1
}

variable "app_max_instances" {
  type    = number
  default = 5
}
```

- [ ] **Step 3.5 : `locals.tf`**

Create `infra/terraform/locals.tf`:

```hcl
locals {
  name_prefix = "webhook-inspector"

  common_labels = {
    app         = "webhook-inspector"
    environment = var.environment
    managed_by  = "terraform"
  }

  # Derived names
  db_instance_name      = "${local.name_prefix}-pg-${var.environment}"
  db_name               = "webhook_inspector"
  db_user               = "webhook"
  artifact_repo_name    = "webhook-inspector"
  blob_bucket_name      = "${var.project_id}-blobs"
  ingestor_service_name = "${local.name_prefix}-ingestor"
  app_service_name      = "${local.name_prefix}-app"
  cleaner_job_name      = "${local.name_prefix}-cleaner"
}
```

- [ ] **Step 3.6 : `apis.tf`**

Create `infra/terraform/apis.tf`:

```hcl
locals {
  required_apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "compute.googleapis.com",
    "cloudbuild.googleapis.com",
  ]
}

resource "google_project_service" "this" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
```

- [ ] **Step 3.7 : `outputs.tf`**

Create `infra/terraform/outputs.tf` (placeholder, filled in later tasks):

```hcl
# Outputs are added incrementally as resources are created.
# This file exists so `terraform output` works from day one.
```

- [ ] **Step 3.8 : `terraform.tfvars.example`**

Create `infra/terraform/terraform.tfvars.example`:

```hcl
# Copy to terraform.tfvars and fill in your value.
# terraform.tfvars is gitignored.

project_id = "webhook-inspector-CHANGEME-dev"
# region, environment, image_tag, db_tier, etc. use sensible defaults.
```

- [ ] **Step 3.9 : Update `.gitignore`**

Append to `.gitignore`:

```
# Terraform
infra/terraform/.terraform/
infra/terraform/.terraform.lock.hcl
infra/terraform/terraform.tfvars
infra/terraform/*.tfstate
infra/terraform/*.tfstate.backup
infra/terraform/crash.log
```

- [ ] **Step 3.10 : `terraform init`**

```bash
cd ~/Work/webhook-inspector/infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and set project_id to your actual ID
terraform init \
  -backend-config="bucket=webhook-inspector-<suffix>-dev-tfstate"
```

Sortie attendue : `Terraform has been successfully initialized!`.

`terraform validate` doit aussi passer :
```bash
terraform validate
```

→ `Success! The configuration is valid.`

- [ ] **Step 3.11 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/versions.tf infra/terraform/backend.tf infra/terraform/variables.tf infra/terraform/locals.tf infra/terraform/apis.tf infra/terraform/outputs.tf infra/terraform/terraform.tfvars.example .gitignore
git commit -m "feat(infra): scaffold Terraform module with GCS backend"
```

---

## Block 3 : Persistence layer

### Task 4 : Service accounts

**Files:**
- Create: `infra/terraform/service_accounts.tf`

Pour une vraie pratique de least privilege, chaque service a son propre service account.

- [ ] **Step 4.1 : `service_accounts.tf`**

Create `infra/terraform/service_accounts.tf`:

```hcl
resource "google_service_account" "ingestor" {
  account_id   = "${local.name_prefix}-ingestor"
  display_name = "Webhook Inspector — Ingestor"
  description  = "Runtime SA for the webhook ingestor service."
}

resource "google_service_account" "app" {
  account_id   = "${local.name_prefix}-app"
  display_name = "Webhook Inspector — App"
  description  = "Runtime SA for the app/UI service."
}

resource "google_service_account" "cleaner" {
  account_id   = "${local.name_prefix}-cleaner"
  display_name = "Webhook Inspector — Cleaner"
  description  = "Runtime SA for the cleaner cron job."
}

resource "google_service_account" "scheduler" {
  account_id   = "${local.name_prefix}-scheduler"
  display_name = "Webhook Inspector — Scheduler"
  description  = "Cloud Scheduler SA to invoke the cleaner job."
}
```

- [ ] **Step 4.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
```

Doit afficher : `Plan: 4 to add, 0 to change, 0 to destroy.` (+ les APIs si pas encore appliquées).

```bash
terraform apply plan.out
```

Vérification :
```bash
gcloud iam service-accounts list --filter="displayName~Webhook"
```

Doit lister les 4 SAs.

- [ ] **Step 4.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/service_accounts.tf
git commit -m "feat(infra): add service accounts for each service"
```

---

### Task 5 : Cloud SQL instance

**Files:**
- Create: `infra/terraform/cloudsql.tf`

- [ ] **Step 5.1 : `cloudsql.tf`**

Create `infra/terraform/cloudsql.tf`:

```hcl
resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = local.db_instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  deletion_protection = false # side-project: allow easy teardown

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL" # no HA in dev
    disk_size         = 10
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false # not on db-f1-micro
      start_time                     = "03:00"
    }

    ip_configuration {
      ipv4_enabled = true
      # No authorized networks → connections go through Cloud SQL Auth Proxy
    }

    database_flags {
      name  = "max_connections"
      value = "100"
    }

    user_labels = local.common_labels
  }
}

resource "google_sql_database" "main" {
  name     = local.db_name
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "main" {
  name     = local.db_user
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
}
```

Add the `random` provider to `versions.tf`:

```hcl
# in versions.tf, inside required_providers:
random = {
  source  = "hashicorp/random"
  version = "~> 3.6"
}
```

- [ ] **Step 5.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform init -upgrade  # to pull random provider
terraform plan -out=plan.out
```

Doit afficher quelques resources à ajouter (instance + db + user + random_password).

```bash
terraform apply plan.out
```

**ATTENTION** : Cloud SQL prend **5-10 minutes** à provisionner. Sois patient. Tant que `terraform apply` n'a pas rendu la main, ne fais rien d'autre.

Vérification :
```bash
gcloud sql instances list
```

L'instance doit apparaître avec status `RUNNABLE`.

- [ ] **Step 5.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/cloudsql.tf infra/terraform/versions.tf
git commit -m "feat(infra): add Cloud SQL Postgres 16 instance with random password"
```

---

### Task 6 : Secret Manager — DATABASE_URL

**Files:**
- Create: `infra/terraform/secret_manager.tf`

Le DATABASE_URL contient le password en clair. Il vit dans Secret Manager, jamais en clair ailleurs (sauf le state TF qui est chiffré au repos par GCS).

- [ ] **Step 6.1 : `secret_manager.tf`**

Create `infra/terraform/secret_manager.tf`:

```hcl
locals {
  # The connection name for Cloud SQL Auth Proxy is
  # "<project>:<region>:<instance>". The proxy creates a Unix socket at
  # /cloudsql/<connection_name>/.s.PGSQL.5432 inside the container.
  cloudsql_socket = "/cloudsql/${google_sql_database_instance.main.connection_name}"
  database_url    = "postgresql+psycopg://${local.db_user}:${random_password.db_password.result}@/${local.db_name}?host=${local.cloudsql_socket}"
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "database-url"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

# Grant access to runtime SAs
resource "google_secret_manager_secret_iam_member" "database_url_app" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url_ingestor" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ingestor.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url_cleaner" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleaner.email}"
}
```

- [ ] **Step 6.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
terraform apply plan.out
```

Vérification :
```bash
gcloud secrets list
gcloud secrets versions access latest --secret=database-url | head -c 40 && echo "..."
```

Doit afficher le début de l'URL : `postgresql+psycopg://webhook:...`.

- [ ] **Step 6.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/secret_manager.tf
git commit -m "feat(infra): store DATABASE_URL in Secret Manager with per-service IAM"
```

---

### Task 7 : GCS bucket pour blobs

**Files:**
- Create: `infra/terraform/gcs.tf`

- [ ] **Step 7.1 : `gcs.tf`**

Create `infra/terraform/gcs.tf`:

```hcl
resource "google_storage_bucket" "blobs" {
  name                        = local.blob_bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  force_destroy               = true # side-project: easy teardown
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      age = var.endpoint_ttl_days # 7 days
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  labels = local.common_labels
}

# Grant write access to ingestor + read access to app
resource "google_storage_bucket_iam_member" "ingestor_writer" {
  bucket = google_storage_bucket.blobs.name
  role   = "roles/storage.objectAdmin" # write + delete (the cleaner needs delete via lifecycle anyway)
  member = "serviceAccount:${google_service_account.ingestor.email}"
}

resource "google_storage_bucket_iam_member" "app_reader" {
  bucket = google_storage_bucket.blobs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.app.email}"
}
```

- [ ] **Step 7.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
terraform apply plan.out
```

Vérification :
```bash
gcloud storage buckets describe "gs://${BUCKET_NAME:-webhook-inspector-<suffix>-dev-blobs}" --format="value(lifecycle.rule[0].action.type, lifecycle.rule[0].condition.age)"
```

Doit afficher `Delete\t7`.

- [ ] **Step 7.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/gcs.tf
git commit -m "feat(infra): add GCS bucket for blobs with 7-day lifecycle deletion"
```

---

### Task 8 : Artifact Registry

**Files:**
- Create: `infra/terraform/artifact_registry.tf`

- [ ] **Step 8.1 : `artifact_registry.tf`**

Create `infra/terraform/artifact_registry.tf`:

```hcl
resource "google_artifact_registry_repository" "main" {
  location      = var.region
  repository_id = local.artifact_repo_name
  description   = "Docker images for webhook-inspector"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-recent-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }

  labels = local.common_labels
}

# Allow Cloud Run service accounts to pull
resource "google_artifact_registry_repository_iam_member" "ingestor_reader" {
  repository = google_artifact_registry_repository.main.name
  location   = google_artifact_registry_repository.main.location
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.ingestor.email}"
}

resource "google_artifact_registry_repository_iam_member" "app_reader" {
  repository = google_artifact_registry_repository.main.name
  location   = google_artifact_registry_repository.main.location
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.app.email}"
}

resource "google_artifact_registry_repository_iam_member" "cleaner_reader" {
  repository = google_artifact_registry_repository.main.name
  location   = google_artifact_registry_repository.main.location
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.cleaner.email}"
}
```

- [ ] **Step 8.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
terraform apply plan.out
```

Vérification :
```bash
gcloud artifacts repositories list --location=europe-west1
```

Doit afficher `webhook-inspector` repo en DOCKER format.

- [ ] **Step 8.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/artifact_registry.tf
git commit -m "feat(infra): add Artifact Registry repository for Docker images"
```

---

### Task 9 : Cloud SQL access IAM

Les service accounts ont besoin du rôle `cloudsql.client` pour utiliser Auth Proxy.

**Files:**
- Modify: `infra/terraform/service_accounts.tf`

- [ ] **Step 9.1 : Ajouter les bindings IAM**

Append to `infra/terraform/service_accounts.tf`:

```hcl
# Cloud SQL client role for runtime SAs that connect to the DB
locals {
  cloudsql_client_sas = [
    google_service_account.ingestor.email,
    google_service_account.app.email,
    google_service_account.cleaner.email,
  ]
}

resource "google_project_iam_member" "cloudsql_client" {
  for_each = toset(local.cloudsql_client_sas)

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${each.value}"
}
```

- [ ] **Step 9.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
terraform apply plan.out
```

Doit afficher `Plan: 3 to add`. Apply rapide (~5s).

Vérification :
```bash
gcloud projects get-iam-policy webhook-inspector-<suffix>-dev \
  --flatten="bindings[].members" \
  --filter="bindings.role=roles/cloudsql.client" \
  --format="value(bindings.members)"
```

Doit lister les 3 SAs.

- [ ] **Step 9.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/service_accounts.tf
git commit -m "feat(infra): grant cloudsql.client role to runtime service accounts"
```

---

## Block 4 : GcsBlobStorage adapter (code Python)

### Task 10 : GcsBlobStorage adapter (TDD)

**Files:**
- Create: `src/webhook_inspector/infrastructure/storage/gcs_blob_storage.py`
- Create: `tests/integration/test_gcs_blob_storage.py`
- Modify: `pyproject.toml` (add `google-cloud-storage` dep)

- [ ] **Step 10.1 : Ajouter la dépendance**

```bash
cd ~/Work/webhook-inspector
uv add google-cloud-storage
```

- [ ] **Step 10.2 : Écrire le test failing**

Create `tests/integration/test_gcs_blob_storage.py`:

```python
"""Integration tests for GcsBlobStorage.

These tests use the `google-cloud-storage` library with a fake in-memory
implementation (`gcsfs` or `fakeredis`-style helpers don't exist for GCS).
Instead, we use a real GCS bucket via Application Default Credentials, or
skip if running without GCP auth.

To run locally, set GCS_TEST_BUCKET to a bucket you can read+write.
In CI, skip (no GCP credentials).
"""

import os
import uuid

import pytest

from webhook_inspector.infrastructure.storage.gcs_blob_storage import GcsBlobStorage

pytestmark = pytest.mark.skipif(
    not os.getenv("GCS_TEST_BUCKET"),
    reason="GCS_TEST_BUCKET not set — skipping live GCS integration tests",
)


@pytest.fixture
def bucket_name() -> str:
    return os.environ["GCS_TEST_BUCKET"]


@pytest.fixture
def test_prefix() -> str:
    # Unique prefix per test run to avoid collisions
    return f"test-{uuid.uuid4()}"


@pytest.fixture
async def storage(bucket_name: str, test_prefix: str) -> GcsBlobStorage:
    return GcsBlobStorage(bucket_name=bucket_name, key_prefix=test_prefix)


async def test_put_then_get_roundtrip(storage: GcsBlobStorage):
    await storage.put("foo/bar", b"hello gcs")
    assert await storage.get("foo/bar") == b"hello gcs"


async def test_get_missing_returns_none(storage: GcsBlobStorage):
    assert await storage.get("does/not/exist") is None


async def test_put_overwrites_existing(storage: GcsBlobStorage):
    await storage.put("key", b"v1")
    await storage.put("key", b"v2")
    assert await storage.get("key") == b"v2"
```

- [ ] **Step 10.3 : Run test, confirm FAIL or SKIP**

```bash
cd ~/Work/webhook-inspector
uv run pytest tests/integration/test_gcs_blob_storage.py -v
```

If `GCS_TEST_BUCKET` is not set: 3 tests skipped. That's expected for now — we'll run them after deploy.

If you want to validate locally now and have ADC set up:
```bash
GCS_TEST_BUCKET=<your-test-bucket> uv run pytest tests/integration/test_gcs_blob_storage.py -v
```

Either way, must NOT have import errors.

- [ ] **Step 10.4 : Implémenter `GcsBlobStorage`**

Create `src/webhook_inspector/infrastructure/storage/gcs_blob_storage.py`:

```python
"""GCS-backed BlobStorage adapter.

Uses google-cloud-storage with asyncio.to_thread to wrap the sync client.
For Phase B, this is acceptable performance-wise (blob writes are off the
hot path of the request). Phase C may switch to gcloud-aio-storage for
native async.
"""

import asyncio

from google.cloud import storage
from google.cloud.exceptions import NotFound

from webhook_inspector.domain.ports.blob_storage import BlobStorage


class GcsBlobStorage(BlobStorage):
    def __init__(self, bucket_name: str, key_prefix: str = "") -> None:
        self._bucket_name = bucket_name
        self._key_prefix = key_prefix.rstrip("/")
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    async def put(self, key: str, data: bytes) -> None:
        full_key = self._full_key(key)
        await asyncio.to_thread(self._upload, full_key, data)

    async def get(self, key: str) -> bytes | None:
        full_key = self._full_key(key)
        try:
            return await asyncio.to_thread(self._download, full_key)
        except NotFound:
            return None

    def _full_key(self, key: str) -> str:
        if self._key_prefix:
            return f"{self._key_prefix}/{key}"
        return key

    def _upload(self, key: str, data: bytes) -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_string(data)

    def _download(self, key: str) -> bytes:
        blob = self._bucket.blob(key)
        return blob.download_as_bytes()
```

- [ ] **Step 10.5 : Verify imports + ruff + mypy**

```bash
cd ~/Work/webhook-inspector
uv run python -c "from webhook_inspector.infrastructure.storage.gcs_blob_storage import GcsBlobStorage; print('ok')"
uv run ruff check src
uv run mypy src
```

All must pass. If mypy complains about `google.cloud.storage` types, add an ignore in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = ["google.cloud.*"]
ignore_missing_imports = true
```

(Append after the existing `[[tool.mypy.overrides]]` if any.)

- [ ] **Step 10.6 : Commit**

```bash
git add src/webhook_inspector/infrastructure/storage/gcs_blob_storage.py tests/integration/test_gcs_blob_storage.py pyproject.toml uv.lock
git commit -m "feat(infra): add GcsBlobStorage adapter for cloud blob persistence"
```

---

### Task 11 : Inject GcsBlobStorage in ingestor when env says so

**Files:**
- Modify: `src/webhook_inspector/config.py` (add `blob_storage_backend` setting)
- Modify: `src/webhook_inspector/web/ingestor/deps.py` (factory choice)
- Create: `tests/unit/test_blob_storage_factory.py`

- [ ] **Step 11.1 : Étendre `Settings`**

Read `src/webhook_inspector/config.py`. Add a new field:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    blob_storage_path: str = "./blobs"
    blob_storage_backend: str = "local"  # "local" or "gcs"
    gcs_bucket_name: str | None = None
    endpoint_ttl_days: int = 7
    max_body_bytes: int = 10 * 1024 * 1024
    body_inline_threshold_bytes: int = 8 * 1024
    environment: str = "local"
    service_name: str = "webhook-inspector"
    log_level: str = "INFO"
```

- [ ] **Step 11.2 : Test du factory**

Create `tests/unit/test_blob_storage_factory.py`:

```python
import os
from unittest.mock import patch

import pytest

from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


def _import_factory():
    # Lazy import so we can re-import after env changes
    from webhook_inspector.infrastructure.storage import factory
    return factory


def test_factory_returns_local_when_backend_is_local(tmp_path):
    env = {
        "BLOB_STORAGE_BACKEND": "local",
        "BLOB_STORAGE_PATH": str(tmp_path),
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings
        settings = Settings()
        storage = _import_factory().make_blob_storage(settings)
        assert isinstance(storage, LocalBlobStorage)


def test_factory_raises_when_gcs_backend_without_bucket():
    env = {
        "BLOB_STORAGE_BACKEND": "gcs",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings
        settings = Settings()
        with pytest.raises(ValueError, match="GCS_BUCKET_NAME"):
            _import_factory().make_blob_storage(settings)


def test_factory_raises_on_unknown_backend():
    env = {
        "BLOB_STORAGE_BACKEND": "redis",
        "DATABASE_URL": "postgresql+psycopg://x:y@h:5432/d",
    }
    with patch.dict(os.environ, env, clear=True):
        from webhook_inspector.config import Settings
        settings = Settings()
        with pytest.raises(ValueError, match="unknown blob storage backend"):
            _import_factory().make_blob_storage(settings)
```

- [ ] **Step 11.3 : Run test, confirm FAIL**

```bash
uv run pytest tests/unit/test_blob_storage_factory.py -v
```

Expected: ImportError on `factory` module.

- [ ] **Step 11.4 : Implémenter le factory**

Create `src/webhook_inspector/infrastructure/storage/factory.py`:

```python
from webhook_inspector.config import Settings
from webhook_inspector.domain.ports.blob_storage import BlobStorage
from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage


def make_blob_storage(settings: Settings) -> BlobStorage:
    backend = settings.blob_storage_backend.lower()
    if backend == "local":
        return LocalBlobStorage(base_path=settings.blob_storage_path)
    if backend == "gcs":
        if not settings.gcs_bucket_name:
            raise ValueError(
                "GCS_BUCKET_NAME must be set when BLOB_STORAGE_BACKEND=gcs"
            )
        # Import here to avoid importing google-cloud-storage when not used
        from webhook_inspector.infrastructure.storage.gcs_blob_storage import (
            GcsBlobStorage,
        )
        return GcsBlobStorage(bucket_name=settings.gcs_bucket_name)
    raise ValueError(f"unknown blob storage backend: {backend!r}")
```

- [ ] **Step 11.5 : Run test, confirm PASS**

```bash
uv run pytest tests/unit/test_blob_storage_factory.py -v
```

Expected: 3 passed.

- [ ] **Step 11.6 : Wire factory into ingestor deps**

Edit `src/webhook_inspector/web/ingestor/deps.py`. Replace the `get_capture_request` function's storage construction:

Find:
```python
from webhook_inspector.infrastructure.storage.local_blob_storage import LocalBlobStorage
# ...
async def get_capture_request(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    notifier: PostgresNotifier = Depends(get_notifier),  # noqa: B008
) -> CaptureRequest:
    return CaptureRequest(
        endpoint_repo=PostgresEndpointRepository(session),
        request_repo=PostgresRequestRepository(session),
        blob_storage=LocalBlobStorage(settings.blob_storage_path),
        notifier=notifier,
        inline_threshold=settings.body_inline_threshold_bytes,
    )
```

Replace with:
```python
from webhook_inspector.infrastructure.storage.factory import make_blob_storage
# (remove the LocalBlobStorage import — no longer needed here)

async def get_capture_request(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    notifier: PostgresNotifier = Depends(get_notifier),  # noqa: B008
) -> CaptureRequest:
    return CaptureRequest(
        endpoint_repo=PostgresEndpointRepository(session),
        request_repo=PostgresRequestRepository(session),
        blob_storage=make_blob_storage(settings),
        notifier=notifier,
        inline_threshold=settings.body_inline_threshold_bytes,
    )
```

- [ ] **Step 11.7 : Verify all tests still pass**

```bash
cd ~/Work/webhook-inspector
uv run pytest tests/ -v
uv run ruff check src tests
uv run mypy src
```

Expected: 48 prior + 3 new = 51 tests passing (locally — integration tests run if Docker is up). Ruff + mypy clean.

- [ ] **Step 11.8 : Commit**

```bash
git add src/webhook_inspector/config.py src/webhook_inspector/infrastructure/storage/factory.py src/webhook_inspector/web/ingestor/deps.py tests/unit/test_blob_storage_factory.py
git commit -m "feat(config): add blob_storage_backend factory (local|gcs)"
```

---

## Block 5 : Cloud Run services + Job

### Task 12 : Build + push first image manually

Avant Terraform les Cloud Run services, on a besoin d'une image dans Artifact Registry, sinon `terraform apply` échoue.

**Files:**
- Create: `scripts/build_and_push.sh`

- [ ] **Step 12.1 : Script build + push**

Create `scripts/build_and_push.sh`:

```bash
#!/usr/bin/env bash
# Build webhook-inspector Docker image and push to Artifact Registry.
#
# Usage: ./scripts/build_and_push.sh <project-id> [tag]
# Default tag: git short SHA.

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <project-id> [tag]}"
TAG="${2:-$(git rev-parse --short HEAD)}"
REGION="europe-west1"
REPO="webhook-inspector"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/webhook-inspector:${TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/webhook-inspector:latest"

echo "==> Configuring docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "==> Building image: $IMAGE"
docker build --platform=linux/amd64 -t "$IMAGE" -t "$IMAGE_LATEST" .

echo "==> Pushing $IMAGE..."
docker push "$IMAGE"
docker push "$IMAGE_LATEST"

echo "==> Done."
echo "Image: $IMAGE"
echo "Tag exported for terraform: $TAG"
```

`--platform=linux/amd64` est important sur Mac M-series (ARM) — Cloud Run gen2 supporte ARM mais pas pour toutes les ressources ; AMD64 reste le défaut sûr.

- [ ] **Step 12.2 : Rendre exécutable**

```bash
chmod +x ~/Work/webhook-inspector/scripts/build_and_push.sh
```

- [ ] **Step 12.3 : Run build + push**

```bash
cd ~/Work/webhook-inspector
./scripts/build_and_push.sh webhook-inspector-<suffix>-dev
```

Note le SHA tag affiché (ex: `abc1234`). On l'utilisera comme `image_tag` dans Terraform.

Vérification :
```bash
gcloud artifacts docker images list \
  europe-west1-docker.pkg.dev/webhook-inspector-<suffix>-dev/webhook-inspector
```

Doit lister `webhook-inspector` avec ton tag.

- [ ] **Step 12.4 : Commit**

```bash
git add scripts/build_and_push.sh
git commit -m "chore(infra): add build+push script for Artifact Registry"
```

---

### Task 13 : Cloud Run service `ingestor`

**Files:**
- Create: `infra/terraform/cloud_run_ingestor.tf`

- [ ] **Step 13.1 : `cloud_run_ingestor.tf`**

Create `infra/terraform/cloud_run_ingestor.tf`:

```hcl
resource "google_cloud_run_v2_service" "ingestor" {
  name     = local.ingestor_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.ingestor.email

    scaling {
      min_instance_count = var.ingestor_min_instances
      max_instance_count = var.ingestor_max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_name}/webhook-inspector:${var.image_tag}"

      command = ["uvicorn"]
      args = [
        "webhook_inspector.web.ingestor.main:app",
        "--host", "0.0.0.0",
        "--port", "8080",
      ]

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
        cpu_idle = true
        startup_cpu_boost = true
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
        name  = "BLOB_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.blobs.name
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "ENDPOINT_TTL_DAYS"
        value = tostring(var.endpoint_ttl_days)
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_iam_member.cloudsql_client,
    google_secret_manager_secret_iam_member.database_url_ingestor,
    google_storage_bucket_iam_member.ingestor_writer,
  ]
}

# Allow unauthenticated invocations (public webhook endpoint)
resource "google_cloud_run_v2_service_iam_member" "ingestor_public" {
  location = google_cloud_run_v2_service.ingestor.location
  name     = google_cloud_run_v2_service.ingestor.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
```

Add to `outputs.tf`:

```hcl
output "ingestor_url" {
  value       = google_cloud_run_v2_service.ingestor.uri
  description = "Public URL of the ingestor service."
}
```

- [ ] **Step 13.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
# Update terraform.tfvars: set image_tag to the SHA you pushed in Task 12
terraform plan -out=plan.out
terraform apply plan.out
```

L'apply prend ~1-2 min (Cloud Run déploie la première révision).

Vérification (le service est UP mais la DB n'a pas encore les tables) :
```bash
INGESTOR_URL=$(terraform output -raw ingestor_url)
echo "Ingestor URL: $INGESTOR_URL"

# Vérifier que le service répond (route inexistante → 404 sans toucher la DB)
curl -sI "${INGESTOR_URL}/" | head -1
```

Doit retourner `HTTP/2 404` (FastAPI default pour route non définie — confirme que le container démarre et répond).

**Note** : si tu testes `curl -X POST .../h/anything`, tu verras un `500` car la table `endpoints` n'existe pas encore — c'est NORMAL à ce stade. Les migrations sont appliquées à Task 16. Les vraies routes fonctionneront après.

⚠️ **Si tu vois autre chose que 404 sur `/`** (502, 503, timeout) : le container ne démarre pas. Check les logs :
```bash
gcloud run services logs read webhook-inspector-ingestor --region=europe-west1 --limit=50
```

Causes courantes :
- Variables d'env mal mappées
- Auth Proxy connection name mal formé
- Container crash au boot (lifespan handler)

- [ ] **Step 13.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/cloud_run_ingestor.tf infra/terraform/outputs.tf
git commit -m "feat(infra): deploy ingestor as public Cloud Run service"
```

---

### Task 14 : Cloud Run service `app`

**Files:**
- Create: `infra/terraform/cloud_run_app.tf`

- [ ] **Step 14.1 : `cloud_run_app.tf`**

Create `infra/terraform/cloud_run_app.tf`:

```hcl
resource "google_cloud_run_v2_service" "app" {
  name     = local.app_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.app.email

    scaling {
      min_instance_count = var.app_min_instances
      max_instance_count = var.app_max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_name}/webhook-inspector:${var.image_tag}"

      command = ["uvicorn"]
      args = [
        "webhook_inspector.web.app.main:app",
        "--host", "0.0.0.0",
        "--port", "8080",
      ]

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
        cpu_idle = false # min=1, keep CPU warm for SSE
        startup_cpu_boost = true
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
        name  = "BLOB_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.blobs.name
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

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_iam_member.cloudsql_client,
    google_secret_manager_secret_iam_member.database_url_app,
    google_storage_bucket_iam_member.app_reader,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "app_public" {
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
```

Add to `outputs.tf`:

```hcl
output "app_url" {
  value       = google_cloud_run_v2_service.app.uri
  description = "Public URL of the app/UI service."
}
```

- [ ] **Step 14.2 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
terraform apply plan.out
```

Vérification (le service est UP) :
```bash
APP_URL=$(terraform output -raw app_url)

# Test sur une route qui ne touche pas la DB
curl -sI "${APP_URL}/" | head -1
```

Doit retourner `HTTP/2 404` (FastAPI 404 sur route racine, sans toucher la DB).

**Note** : `POST /api/endpoints` retournera 500 jusqu'à ce que les migrations soient appliquées en Task 16. Normal.

- [ ] **Step 14.3 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/cloud_run_app.tf infra/terraform/outputs.tf
git commit -m "feat(infra): deploy app as public Cloud Run service"
```

---

### Task 15 : Cloud Run Job `cleaner` + Cloud Scheduler

**Files:**
- Create: `infra/terraform/cloud_run_cleaner.tf`
- Create: `infra/terraform/cloud_scheduler.tf`

- [ ] **Step 15.1 : `cloud_run_cleaner.tf`**

Create `infra/terraform/cloud_run_cleaner.tf`:

```hcl
resource "google_cloud_run_v2_job" "cleaner" {
  name     = local.cleaner_job_name
  location = var.region

  template {
    template {
      service_account = google_service_account.cleaner.email

      max_retries = 1
      timeout     = "300s"

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repo_name}/webhook-inspector:${var.image_tag}"

        command = ["python"]
        args    = ["-m", "webhook_inspector.jobs.cleaner"]

        resources {
          limits = {
            cpu    = "1000m"
            memory = "256Mi"
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
        env {
          name  = "ENDPOINT_TTL_DAYS"
          value = tostring(var.endpoint_ttl_days)
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
```

- [ ] **Step 15.2 : `cloud_scheduler.tf`**

Create `infra/terraform/cloud_scheduler.tf`:

```hcl
# Allow Cloud Scheduler to invoke the cleaner job
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  location = google_cloud_run_v2_job.cleaner.location
  name     = google_cloud_run_v2_job.cleaner.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "cleaner_daily" {
  name             = "${local.cleaner_job_name}-daily"
  region           = var.region
  description      = "Run cleaner job daily at 03:00 UTC."
  schedule         = "0 3 * * *"
  time_zone        = "UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.cleaner.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_cloud_run_v2_job_iam_member.scheduler_invoker,
  ]
}
```

- [ ] **Step 15.3 : Plan + apply**

```bash
cd ~/Work/webhook-inspector/infra/terraform
terraform plan -out=plan.out
terraform apply plan.out
```

Vérification :
```bash
gcloud run jobs list --region=europe-west1
gcloud scheduler jobs list --location=europe-west1
```

Doit lister `webhook-inspector-cleaner` job et `webhook-inspector-cleaner-daily` scheduler.

- [ ] **Step 15.4 : Test job manuel (sera ré-exécuté après migration)**

À ce stade, le job va échouer parce que la table `endpoints` n'existe pas (migration appliquée en Task 16). On vérifie juste que le job est correctement configuré et exécutable :

```bash
gcloud run jobs execute webhook-inspector-cleaner --region=europe-west1 --wait || true
```

Attendu : execution termine en `Failed` avec une erreur SQL "relation does not exist".

Vérification que le job a au moins TENTÉ de tourner :
```bash
gcloud run jobs executions list --job=webhook-inspector-cleaner --region=europe-west1 --limit=1
```

Doit afficher 1 execution récente (status Failed, mais c'est attendu).

Logs détaillés :
```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=webhook-inspector-cleaner' --limit=20 --format="value(textPayload)"
```

Tu dois voir l'erreur SQL. Si tu vois autre chose (container crash, IAM denied), c'est un vrai problème.

Le job sera re-testé en succès après Task 16 (migration appliquée).

- [ ] **Step 15.5 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/cloud_run_cleaner.tf infra/terraform/cloud_scheduler.tf
git commit -m "feat(infra): deploy cleaner Cloud Run Job + Scheduler daily trigger"
```

---

## Block 6 : Migration + smoke test cloud

### Task 16 : Appliquer les migrations Alembic contre Cloud SQL

**Files:**
- Create: `scripts/run_migration.sh`

L'approche pragmatique : utiliser `cloud-sql-proxy` localement pour ouvrir un tunnel vers Cloud SQL, puis lancer alembic depuis ta machine.

- [ ] **Step 16.1 : Installer cloud-sql-proxy**

Sur macOS :
```bash
brew install cloud-sql-proxy
cloud-sql-proxy --version
```

- [ ] **Step 16.2 : Script migration**

Create `scripts/run_migration.sh`:

```bash
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
sleep 3

echo "==> Running alembic upgrade head..."
PGPASSWORD="$DB_PASSWORD" DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@localhost:${LOCAL_PORT}/${DB_NAME}" \
  uv run alembic upgrade head

echo "==> Done. Tables:"
PGPASSWORD="$DB_PASSWORD" psql -h localhost -p "$LOCAL_PORT" -U "$DB_USER" -d "$DB_NAME" -c "\dt"
```

```bash
chmod +x ~/Work/webhook-inspector/scripts/run_migration.sh
```

- [ ] **Step 16.3 : Exécuter migrations**

```bash
cd ~/Work/webhook-inspector
./scripts/run_migration.sh webhook-inspector-<suffix>-dev
```

Sortie attendue : `Running upgrade  -> 19068e2673bf, initial schema` puis listing `endpoints requests alembic_version`.

- [ ] **Step 16.4 : Commit**

```bash
git add scripts/run_migration.sh
git commit -m "chore(infra): add Cloud SQL migration script via cloud-sql-proxy"
```

---

### Task 17 : Smoke test sur le cloud

**Files:**
- Create: `scripts/smoke_test_cloud.sh`

- [ ] **Step 17.1 : Script smoke test**

Create `scripts/smoke_test_cloud.sh`:

```bash
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
```

```bash
chmod +x ~/Work/webhook-inspector/scripts/smoke_test_cloud.sh
```

- [ ] **Step 17.2 : Run smoke test**

```bash
cd ~/Work/webhook-inspector
./scripts/smoke_test_cloud.sh webhook-inspector-<suffix>-dev
```

Sortie attendue :
- Step 1 : JSON `{url, token, expires_at}`
- Step 2 : Trois HTTP 200
- Step 3 : Liste avec 3 entrées (méthode POST, paths `/h/<token>`)
- Step 4 : URL viewer affiché

Ouvre l'URL viewer dans le navigateur. Tu dois voir les 3 lignes.

- [ ] **Step 17.3 : Test le cleaner job manuellement**

```bash
gcloud run jobs execute webhook-inspector-cleaner --region=europe-west1 --wait
```

Doit terminer en `Succeeded`. Logs :
```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=webhook-inspector-cleaner' \
  --limit=10 --format="value(textPayload, jsonPayload.event)" --order=desc
```

Doit afficher `cleanup_complete` avec `deleted=0` (rien n'a encore expiré).

- [ ] **Step 17.4 : Commit**

```bash
git add scripts/smoke_test_cloud.sh
git commit -m "test(infra): add cloud smoke test script for deployed services"
```

---

## Block 7 : Documentation + récap

### Task 18 : README pour `infra/terraform/`

**Files:**
- Create: `infra/terraform/README.md`

- [ ] **Step 18.1 : Écrire le README infra**

Create `infra/terraform/README.md`:

```markdown
# Infrastructure — webhook-inspector (Phase B)

Terraform module deploying webhook-inspector to GCP in a single `dev` env.

## Prerequisites

- GCP project created with billing enabled and a budget alert.
- `gcloud` CLI authenticated (`gcloud auth login` + `gcloud auth application-default login`).
- Terraform >= 1.10.
- Docker (for building images).

## First-time setup

```bash
# 1. Bootstrap APIs + state bucket (run from repo root)
./scripts/bootstrap_gcp.sh <project-id>

# 2. Set up Terraform vars
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set project_id to your actual GCP project ID

# 3. Initialize Terraform
terraform init -backend-config="bucket=<project-id>-tfstate"

# 4. Build and push the first image (from repo root)
cd ../..
./scripts/build_and_push.sh <project-id>
# Note the tag printed at the end and update image_tag in terraform.tfvars.

# 5. Apply
cd infra/terraform
terraform apply

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
terraform apply
```

## Tearing down

```bash
cd infra/terraform
terraform destroy
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
```

- [ ] **Step 18.2 : Commit**

```bash
cd ~/Work/webhook-inspector
git add infra/terraform/README.md
git commit -m "docs(infra): add Terraform module README with setup + cost guide"
```

---

## Self-review

(Run after writing the plan — fix inline.)

**1. Spec coverage**

- GCP project + billing + budget : Task 1 ✓
- Bootstrap state bucket + APIs : Task 2 ✓
- Terraform module structure : Task 3 ✓
- Service accounts + IAM least privilege : Tasks 4, 9 ✓
- Cloud SQL `db-f1-micro` single-zone : Task 5 ✓
- Secret Manager DATABASE_URL : Task 6 ✓
- GCS bucket + 7d lifecycle : Task 7 ✓
- Artifact Registry : Task 8 ✓
- GcsBlobStorage adapter : Task 10 ✓
- Storage factory (local/gcs) : Task 11 ✓
- Build + push image : Task 12 ✓
- Cloud Run ingestor : Task 13 ✓
- Cloud Run app : Task 14 ✓
- Cloud Run Job cleaner + Scheduler : Task 15 ✓
- Migration : Task 16 ✓
- Smoke test cloud : Task 17 ✓
- Infrastructure README : Task 18 ✓

**Out of scope (Phase C)** : CI/CD GitHub Actions, Workload Identity Federation, Cloudflare DNS, OTLP Cloud Trace export.

**2. Type consistency**

- `make_blob_storage(settings)` signature consistent across Task 11 callsites.
- `GcsBlobStorage` constructor : `(bucket_name, key_prefix="")`, used as `GcsBlobStorage(bucket_name=settings.gcs_bucket_name)` (no prefix) in factory. Consistent.
- Terraform local names match across files (`local.ingestor_service_name`, etc.).

**3. Aucun placeholder détecté**.

---

## Next Steps (Phase C)

Une fois Phase B déployée et stable, attaquer Phase C :

1. **GitHub Actions deploy workflows** : `deploy-dev.yml` (push develop) et `deploy-prod.yml` (push main, manual approval).
2. **Workload Identity Federation** : authentification GH Actions ↔ GCP sans clé JSON.
3. **Domaine + DNS Cloudflare** : `app.<domain>` et `hook.<domain>`, TLS auto.
4. **OTLP exporter** vers Cloud Trace + Cloud Logging structured ingestion.
5. **`prod` environment** : duplication du module Terraform en `prod/` ou via workspaces.
6. **Health checks + uptime monitoring** : premier SLI/SLO.
