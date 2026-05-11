from fastapi import FastAPI

from webhook_inspector.web.ingestor.routes import router

app = FastAPI(title="Webhook Inspector — Ingestor")
app.include_router(router)
