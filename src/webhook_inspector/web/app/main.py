from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from webhook_inspector.config import Settings
from webhook_inspector.observability.logging import configure_logging
from webhook_inspector.observability.tracing import configure_tracing, instrument_app
from webhook_inspector.web.app.deps import _engine
from webhook_inspector.web.app.routes import router

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.log_level, settings.service_name + "-app")
    configure_tracing(settings.service_name + "-app", settings.environment, settings.cloud_trace_enabled)
    instrument_app(app, _engine())
    yield


app = FastAPI(title="Webhook Inspector — App", lifespan=lifespan)
app.state.templates = templates
app.include_router(router)
