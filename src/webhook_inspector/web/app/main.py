from fastapi import FastAPI

from webhook_inspector.web.app.routes import router

app = FastAPI(title="Webhook Inspector — App")
app.include_router(router)
