from fastapi import FastAPI
from routers import health, matrix, outreach, webhooks
from config import get_settings

settings = get_settings()

app = FastAPI(
    title="Sediment Briefing API",
    description="API de outreach para Sediment Data — selección de mensajes, cascade de emails y webhooks de Instantly",
    version="1.0.0",
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url=None,
)

app.include_router(health.router)
app.include_router(matrix.router, prefix="/matrix", tags=["Matrix"])
app.include_router(outreach.router, prefix="/outreach", tags=["Outreach"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
