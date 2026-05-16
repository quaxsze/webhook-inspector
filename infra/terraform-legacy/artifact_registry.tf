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
