from opentelemetry.metrics import MeterProvider
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from webhook_inspector.infrastructure.observability.otel_metrics_collector import (
    OtelMetricsCollector,
)


def _build_collector() -> tuple[OtelMetricsCollector, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider: MeterProvider = SdkMeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    collector = OtelMetricsCollector(meter)
    return collector, reader


def _metric_data_points(reader: InMemoryMetricReader, name: str):
    metrics = reader.get_metrics_data()
    for rm in metrics.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    return list(m.data.data_points)
    return []


def test_endpoint_created_increments_counter():
    collector, reader = _build_collector()
    collector.endpoint_created()
    collector.endpoint_created()
    points = _metric_data_points(reader, "webhook_inspector.endpoints.created")
    assert sum(p.value for p in points) == 2


def test_request_captured_records_with_labels():
    collector, reader = _build_collector()
    collector.request_captured(
        method="POST", body_offloaded=False, body_size=100, duration_seconds=0.05
    )
    captured = _metric_data_points(reader, "webhook_inspector.requests.captured")
    assert any(
        p.attributes.get("method") == "POST"
        and p.attributes.get("body_offloaded") is False
        and p.value == 1
        for p in captured
    )
    body_size = _metric_data_points(reader, "webhook_inspector.requests.body_size_bytes")
    assert any(p.sum == 100 for p in body_size)
    duration = _metric_data_points(reader, "webhook_inspector.requests.capture_duration_seconds")
    assert any(p.sum == 0.05 for p in duration)


def test_cleaner_run_emits_heartbeat_and_deletions():
    collector, reader = _build_collector()
    collector.cleaner_run(deleted=3)
    runs = _metric_data_points(reader, "webhook_inspector.cleaner.runs.completed")
    deletions = _metric_data_points(reader, "webhook_inspector.cleaner.deletions")
    assert sum(p.value for p in runs) == 1
    assert sum(p.value for p in deletions) == 3


def test_cleaner_run_with_zero_deletions_still_emits_heartbeat():
    collector, reader = _build_collector()
    collector.cleaner_run(deleted=0)
    runs = _metric_data_points(reader, "webhook_inspector.cleaner.runs.completed")
    assert sum(p.value for p in runs) == 1
