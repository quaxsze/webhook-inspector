"""Metrics provider configuration. Mirrors the pattern in tracing.py.

In prod (CLOUD_METRICS_ENABLED=true), exports to Cloud Monitoring via
opentelemetry-exporter-gcp-monitoring (uses ADC, no manual auth).
With OTLP_ENDPOINT set, exports via OTLP/HTTP (e.g. Honeycomb).
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


def _build_meter_provider(
    service_name: str,
    cloud_metrics_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
) -> MeterProvider:
    resource = Resource.create({"service.name": service_name})

    exporter: MetricExporter
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )

        exporter = OTLPMetricExporter(
            endpoint=f"{otlp_endpoint.rstrip('/')}/v1/metrics",
            headers=_parse_headers(otlp_headers),
        )
    elif cloud_metrics_enabled:
        from opentelemetry.exporter.cloud_monitoring import (
            CloudMonitoringMetricsExporter,
        )

        exporter = CloudMonitoringMetricsExporter()
    else:
        exporter = ConsoleMetricExporter()

    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    return MeterProvider(resource=resource, metric_readers=[reader])


def configure_metrics(
    service_name: str,
    cloud_metrics_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
) -> None:
    """Configure the global MeterProvider for the running process."""
    global _provider
    _provider = _build_meter_provider(
        service_name=service_name,
        cloud_metrics_enabled=cloud_metrics_enabled,
        otlp_endpoint=otlp_endpoint,
        otlp_headers=otlp_headers,
    )
    metrics.set_meter_provider(_provider)


def _parse_headers(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def force_flush_metrics(timeout_millis: int = 5000) -> None:
    """Flush any pending metric exports. Critical for short-lived jobs."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=timeout_millis)
