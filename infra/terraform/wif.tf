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
    "roles/run.admin",                    # deploy/update Cloud Run services + jobs
    "roles/artifactregistry.writer",      # push images
    "roles/secretmanager.secretAccessor", # read DATABASE_URL secret value during deploy validations
    "roles/secretmanager.viewer",         # read secret resource metadata (needed by tofu refresh)
    "roles/cloudsql.client",              # connect via Auth Proxy for migrations
    "roles/iam.serviceAccountUser",       # actAs the runtime SAs (assigned to Cloud Run)
    "roles/iam.securityReviewer",         # read project IAM policy (needed by tofu refresh on iam_member resources)
    "roles/storage.admin",                # tofu state bucket access (read/write)
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
