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
