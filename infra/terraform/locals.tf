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
