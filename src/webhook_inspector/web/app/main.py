from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from webhook_inspector.web.app.routes import router

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="Webhook Inspector — App")
app.state.templates = templates
app.include_router(router)
