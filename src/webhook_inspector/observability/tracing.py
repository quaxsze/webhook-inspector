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
from sqlalchemy.ext.asyncio import AsyncEngine


def configure_tracing(
    service_name: str, environment: str, cloud_trace_enabled: bool = False
) -> None:
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)

    if cloud_trace_enabled:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))  # type: ignore[no-untyped-call]
    else:
        # SimpleSpanProcessor for console: synchronous, no daemon thread.
        # Avoids stdout-already-closed errors when pytest exits.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


def instrument_app(app: FastAPI, engine: AsyncEngine | None = None) -> None:
    FastAPIInstrumentor.instrument_app(app)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
