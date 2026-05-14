resource "google_monitoring_notification_channel" "email_owner" {
  display_name = "Owner email"
  type         = "email"
  labels = {
    email_address = var.owner_email
  }
}

# Alert 1 — High p95 ingest latency
resource "google_monitoring_alert_policy" "high_p95_latency" {
  display_name = "High p95 ingest latency"
  combiner     = "OR"
  conditions {
    display_name = "p95 > 1s for 5 min"
    condition_threshold {
      filter          = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.capture_duration_seconds\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 1.0
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
}

# Alert 2 — High 5xx rate (ingestor)
resource "google_monitoring_alert_policy" "high_5xx_rate" {
  display_name = "High 5xx rate (ingestor)"
  combiner     = "OR"
  conditions {
    display_name = "5xx rate > 5% for 5 min"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"webhook-inspector-ingestor\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.5 # raw count, not ratio; adjust after first observation
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "critical" }
}

# Alert 3 — Cloud SQL CPU sustained high (tier-upgrade signal)
# Threshold aligned with the db_tier variable description: bump to
# db-custom-1-1740 when CPU stays above 70% (sustained 10 min).
resource "google_monitoring_alert_policy" "cloudsql_cpu" {
  display_name = "Cloud SQL CPU > 70% sustained (10min) — consider tier upgrade"
  combiner     = "OR"
  conditions {
    display_name = "CPU > 70% for 10 min"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\" AND resource.type=\"cloudsql_database\""
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.70
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MEAN"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = ["resource.label.database_id"]
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
  documentation {
    content   = "Cloud SQL CPU has been above 70% for 10 minutes. Per the `db_tier` variable description in `variables.tf`, consider upgrading from `db-f1-micro` to `db-custom-1-1740` (1 vCPU / 1.7 GB)."
    mime_type = "text/markdown"
  }
}

# Alert 4 — Cloud SQL query latency p95 (tier-upgrade signal)
# Threshold aligned with the db_tier variable description: bump to
# db-custom-1-1740 when query latency p95 exceeds 200ms.
# Metric: cloudsql.googleapis.com/database/postgresql/insights/aggregate/latencies
# is a DISTRIBUTION metric exposed by Cloud SQL Insights (enabled on
# google_sql_database_instance.main via insights_config). Reported in
# microseconds, so 200ms = 200000.
resource "google_monitoring_alert_policy" "cloudsql_query_latency_p95" {
  display_name = "Cloud SQL query latency p95 > 200ms (5min) — consider tier upgrade"
  combiner     = "OR"
  conditions {
    display_name = "Query latency p95 > 200ms for 5 min"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/postgresql/insights/aggregate/latencies\" AND resource.type=\"cloudsql_instance_database\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 200000 # microseconds → 200 ms
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = ["resource.label.database_id"]
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
  documentation {
    content   = "Cloud SQL query latency p95 has been above 200ms for 5 minutes. Per the `db_tier` variable description in `variables.tf`, consider upgrading from `db-f1-micro` to `db-custom-1-1740` (1 vCPU / 1.7 GB). Metric source: Cloud SQL Insights (enabled in `cloudsql.tf` via `insights_config`)."
    mime_type = "text/markdown"
  }
}

# Alert 5 — Cloud SQL disk
resource "google_monitoring_alert_policy" "cloudsql_disk" {
  display_name = "Cloud SQL disk pressure"
  combiner     = "OR"
  conditions {
    display_name = "Disk > 90%"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.9
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "critical" }
}

# Alert 6 — Cleaner stale (heartbeat absent)
resource "google_monitoring_alert_policy" "cleaner_stale" {
  display_name = "Cleaner job not running"
  combiner     = "OR"
  conditions {
    display_name = "No cleaner.runs.completed datapoint in 26h"
    condition_absent {
      filter   = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.cleaner.runs.completed\""
      duration = "93600s" # 26h
      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
}
