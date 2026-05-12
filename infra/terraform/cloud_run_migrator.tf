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
