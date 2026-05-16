from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from sqlalchemy.ext.asyncio import AsyncEngine


def _build_tracer_provider(
    service_name: str,
    environment: str,
    cloud_trace_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    sample_ratio: float = 0.1,
) -> TracerProvider:
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )
    # 10% sampling stays well under Cloud Trace's 2.5M spans/month free tier
    # even at 10x current traffic. Set TRACE_SAMPLE_RATIO=1.0 in dev for full traces.
    provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(sample_ratio))

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces",
                    headers=_parse_headers(otlp_headers),
                )
            )
        )
    elif cloud_trace_enabled:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))  # type: ignore[no-untyped-call]
    else:
        # SimpleSpanProcessor for console: synchronous, no daemon thread.
        # Avoids stdout-already-closed errors when pytest exits.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    return provider


def configure_tracing(
    service_name: str,
    environment: str,
    cloud_trace_enabled: bool = False,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    sample_ratio: float = 0.1,
) -> None:
    provider = _build_tracer_provider(
        service_name=service_name,
        environment=environment,
        cloud_trace_enabled=cloud_trace_enabled,
        otlp_endpoint=otlp_endpoint,
        otlp_headers=otlp_headers,
        sample_ratio=sample_ratio,
    )
    trace.set_tracer_provider(provider)


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


def instrument_app(app: FastAPI, engine: AsyncEngine | None = None) -> None:
    FastAPIInstrumentor.instrument_app(app)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
