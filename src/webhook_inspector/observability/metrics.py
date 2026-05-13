"""Metrics provider configuration. Mirrors the pattern in tracing.py.

In prod (CLOUD_METRICS_ENABLED=true), exports to Cloud Monitoring via
opentelemetry-exporter-gcp-monitoring (uses ADC, no manual auth).
In local/test, uses ConsoleMetricExporter (stdout) on a 60s interval.
"""

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

_provider: MeterProvider | None = None


def configure_metrics(service_name: str, cloud_metrics_enabled: bool = False) -> None:
    """Configure the global MeterProvider for the running process."""
    global _provider

    resource = Resource.create({"service.name": service_name})

    exporter: MetricExporter
    if cloud_metrics_enabled:
        from opentelemetry.exporter.cloud_monitoring import (
            CloudMonitoringMetricsExporter,
        )

        exporter = CloudMonitoringMetricsExporter()
    else:
        exporter = ConsoleMetricExporter()

    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    _provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_provider)


def force_flush_metrics(timeout_millis: int = 5000) -> None:
    """Flush any pending metric exports. Critical for short-lived jobs."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=timeout_millis)
