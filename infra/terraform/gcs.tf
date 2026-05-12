resource "google_storage_bucket" "blobs" {
  name                        = local.blob_bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  force_destroy               = true # side-project: easy teardown
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      age = var.endpoint_ttl_days # 7 days
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = false
  }

  labels = local.common_labels
}

# Grant write access to ingestor + read access to app
resource "google_storage_bucket_iam_member" "ingestor_writer" {
  bucket = google_storage_bucket.blobs.name
  role   = "roles/storage.objectCreator" # least privilege: write-only. GCS lifecycle handles deletes.
  member = "serviceAccount:${google_service_account.ingestor.email}"
}

resource "google_storage_bucket_iam_member" "app_reader" {
  bucket = google_storage_bucket.blobs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.app.email}"
}
