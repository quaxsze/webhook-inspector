# Cloud Monitoring dashboard for webhook-inspector.
# 12 tiles in a 4×3 mosaic grid.
# Custom metrics (custom.googleapis.com/opentelemetry/...) come from the
# Python services via opentelemetry-exporter-gcp-monitoring.

resource "google_monitoring_dashboard" "main" {
  dashboard_json = jsonencode({
    displayName = "webhook-inspector"
    mosaicLayout = {
      columns = 12
      tiles = [
        # Row 1
        {
          width = 4, height = 4, xPos = 0, yPos = 0,
          widget = {
            title = "Requests captured / min"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.captured\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 0,
          widget = {
            title = "Endpoints created / min"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.endpoints.created\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 0,
          widget = {
            title = "Active endpoints"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.endpoints.active\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 2
        {
          width = 4, height = 4, xPos = 0, yPos = 4,
          widget = {
            title = "Ingest duration p50/p95/p99"
            xyChart = {
              dataSets = [
                for pct in ["50", "95", "99"] : {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.capture_duration_seconds\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_${pct}"
                      }
                    }
                  }
                  plotType   = "LINE"
                  legendTemplate = "p${pct}"
                }
              ]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 4,
          widget = {
            title = "Body size distribution (mean)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.requests.body_size_bytes\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 4,
          widget = {
            title = "SSE active connections"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.sse.active_connections\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 3
        {
          width = 4, height = 4, xPos = 0, yPos = 8,
          widget = {
            title = "Cloud Run 5xx (ingestor)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"webhook-inspector-ingestor\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 8,
          widget = {
            title = "Cloud SQL CPU %"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 8,
          widget = {
            title = "Cloud SQL connections"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 4
        {
          width = 4, height = 4, xPos = 0, yPos = 12,
          widget = {
            title = "Cleaner deletions / day"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/opentelemetry/webhook_inspector.cleaner.deletions\""
                    aggregation = {
                      alignmentPeriod  = "86400s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "STACKED_BAR"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 4, yPos = 12,
          widget = {
            title = "Cloud Run instance count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/container/instance_count\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_MEAN"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["resource.label.service_name"]
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 4, height = 4, xPos = 8, yPos = 12,
          widget = {
            title = "Log error rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/log_entry_count\" AND metric.labels.severity=\"ERROR\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        }
      ]
    }
  })
}

output "dashboard_url" {
  value = "https://console.cloud.google.com/monitoring/dashboards/builder/${basename(google_monitoring_dashboard.main.id)}?project=${var.project_id}"
}
