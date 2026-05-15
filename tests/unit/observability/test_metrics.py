from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from webhook_inspector.observability.metrics import _build_meter_provider


def _exporter_class_names(provider: MeterProvider) -> list[str]:
    readers = provider._sdk_config.metric_readers  # type: ignore[attr-defined]
    out: list[str] = []
    for r in readers:
        if isinstance(r, PeriodicExportingMetricReader):
            exporter = getattr(r, "_exporter", None)
            if exporter is not None:
                out.append(type(exporter).__name__)
    return out


def test_otlp_endpoint_builds_otlp_exporter():
    provider = _build_meter_provider(
        service_name="test-svc",
        otlp_endpoint="https://api.honeycomb.io",
        otlp_headers="x-honeycomb-team=abc",
    )
    assert isinstance(provider, MeterProvider)
    names = _exporter_class_names(provider)
    assert any("OTLPMetricExporter" in n for n in names), names


def test_no_otlp_no_cloud_metrics_falls_back_to_console():
    provider = _build_meter_provider(service_name="test-svc")
    assert isinstance(provider, MeterProvider)
    names = _exporter_class_names(provider)
    assert any("ConsoleMetricExporter" in n for n in names), names
