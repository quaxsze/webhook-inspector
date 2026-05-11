from fastapi import FastAPI

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.ingestor.deps import _engine
from webhook_inspector.web.ingestor.routes import router

_settings = Settings()
configure_logging(_settings.log_level, _settings.service_name + "-ingestor")
configure_tracing(_settings.service_name + "-ingestor", _settings.environment, None)

app = FastAPI(title="Webhook Inspector — Ingestor")
app.include_router(router)
instrument_app(app, _engine())
