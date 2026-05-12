# Outputs are added incrementally as resources are created.
# This file exists so `terraform output` works from day one.

output "ingestor_url" {
  value       = google_cloud_run_v2_service.ingestor.uri
  description = "Public URL of the ingestor service."
}

output "app_url" {
  value       = google_cloud_run_v2_service.app.uri
  description = "Public URL of the app/UI service."
}
