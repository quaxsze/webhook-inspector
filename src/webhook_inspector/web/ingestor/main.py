from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.ingestor.deps import _engine
from webhook_inspector.web.ingestor.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-ingestor")
    configure_tracing(settings.service_name + "-ingestor", settings.environment, settings.cloud_trace_enabled)
    instrument_app(app, _engine())
    yield


app = FastAPI(title="Webhook Inspector — Ingestor", lifespan=lifespan)
app.include_router(router)
