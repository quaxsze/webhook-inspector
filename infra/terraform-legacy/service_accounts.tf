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

# Cloud Trace agent role for all runtime SAs (least-privilege trace writes)
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

# Cloud Monitoring write access for runtime SAs (metrics export)
locals {
  monitoring_writer_sas = [
    google_service_account.ingestor.email,
    google_service_account.app.email,
    google_service_account.cleaner.email,
  ]
}

resource "google_project_iam_member" "monitoring_writer" {
  for_each = toset(local.monitoring_writer_sas)
  project  = var.project_id
  role     = "roles/monitoring.metricWriter"
  member   = "serviceAccount:${each.value}"
}
