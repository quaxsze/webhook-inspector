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

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_iam_member.cloudsql_client,
    google_project_iam_member.trace_writer,
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
