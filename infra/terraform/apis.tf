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
    "cloudtrace.googleapis.com",
  ]
}

resource "google_project_service" "this" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
