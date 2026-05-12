locals {
  # The connection name for Cloud SQL Auth Proxy is
  # "<project>:<region>:<instance>". The proxy creates a Unix socket at
  # /cloudsql/<connection_name>/.s.PGSQL.5432 inside the container.
  cloudsql_socket = "/cloudsql/${google_sql_database_instance.main.connection_name}"
  database_url    = "postgresql+psycopg://${local.db_user}:${random_password.db_password.result}@/${local.db_name}?host=${local.cloudsql_socket}"
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "database-url"
  replication {
    auto {}
  }
  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

# Grant access to runtime SAs
resource "google_secret_manager_secret_iam_member" "database_url_app" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url_ingestor" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ingestor.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url_cleaner" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cleaner.email}"
}
