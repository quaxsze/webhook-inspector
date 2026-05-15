resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = local.db_instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  deletion_protection = false # side-project: allow easy teardown

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE" # required for shared-core tiers like db-f1-micro
    availability_type = "ZONAL"      # no HA in dev
    disk_size         = 10
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false # not on db-f1-micro
      start_time                     = "03:00"
    }

    ip_configuration {
      ipv4_enabled = true
      # No authorized networks → connections go through Cloud SQL Auth Proxy
    }

    database_flags {
      name  = "max_connections"
      value = "100"
    }

    # Cloud SQL Insights — free on db-f1-micro; required for the
    # postgresql/insights/aggregate/latencies distribution metric used by the
    # "Cloud SQL query latency p95" alert (see monitoring_alerts.tf).
    insights_config {
      query_insights_enabled  = true
      query_plans_per_minute  = 5
      query_string_length     = 1024
      record_application_tags = false
      record_client_address   = false
    }

    user_labels = local.common_labels
  }
}

resource "google_sql_database" "main" {
  name     = local.db_name
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "main" {
  name     = local.db_user
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
}
