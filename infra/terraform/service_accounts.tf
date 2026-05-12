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
