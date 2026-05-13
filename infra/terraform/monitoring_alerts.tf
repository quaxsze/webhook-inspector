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

# Alert 3 — Cloud SQL CPU
resource "google_monitoring_alert_policy" "cloudsql_cpu" {
  display_name = "Cloud SQL CPU saturated"
  combiner     = "OR"
  conditions {
    display_name = "CPU > 80% for 10 min"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email_owner.id]
  user_labels           = { severity = "warning" }
}

# Alert 4 — Cloud SQL disk
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

# Alert 5 — Cleaner stale (heartbeat absent)
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
