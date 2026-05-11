from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.app.deps import _engine
from webhook_inspector.web.app.routes import router

_settings = Settings()
configure_logging(_settings.log_level, _settings.service_name + "-app")
configure_tracing(_settings.service_name + "-app", _settings.environment, None)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="Webhook Inspector — App")
app.state.templates = templates
app.include_router(router)
instrument_app(app, _engine())
