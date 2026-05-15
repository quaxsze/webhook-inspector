from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

from webhook_inspector.observability.tracing import _build_tracer_provider


def _exporter_class_names(provider: TracerProvider) -> list[str]:
    """Walk the active span processor and return the exporter class names."""
    multi = provider._active_span_processor  # type: ignore[attr-defined]
    processors = getattr(multi, "_span_processors", [multi])
    out: list[str] = []
    for proc in processors:
        if isinstance(proc, (BatchSpanProcessor, SimpleSpanProcessor)):
            exporter = getattr(proc, "span_exporter", None) or getattr(proc, "_exporter", None)
            if exporter is not None:
                out.append(type(exporter).__name__)
    return out


def test_otlp_endpoint_builds_otlp_exporter():
    provider = _build_tracer_provider(
        service_name="test-svc",
        environment="test",
        otlp_endpoint="https://api.honeycomb.io",
        otlp_headers="x-honeycomb-team=abc",
    )
    assert isinstance(provider, TracerProvider)
    names = _exporter_class_names(provider)
    assert any("OTLPSpanExporter" in n for n in names), names


def test_no_otlp_no_cloud_trace_falls_back_to_console():
    provider = _build_tracer_provider(
        service_name="test-svc",
        environment="test",
        otlp_endpoint=None,
        cloud_trace_enabled=False,
    )
    assert isinstance(provider, TracerProvider)
    names = _exporter_class_names(provider)
    assert any("ConsoleSpanExporter" in n for n in names), names
