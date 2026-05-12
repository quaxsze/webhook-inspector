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
        env {
          name  = "ENDPOINT_TTL_DAYS"
          value = tostring(var.endpoint_ttl_days)
        }
        env {
          name  = "CLOUD_TRACE_ENABLED"
          value = "true"
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
    google_project_iam_member.trace_writer,
    google_secret_manager_secret_iam_member.database_url_cleaner,
  ]
}
