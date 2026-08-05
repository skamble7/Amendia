# app/main.py
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from amendia_telemetry import configure_telemetry

from app.routers.config_routes import router as config_router
from app.config import settings
from app.logging_conf import *  # configure root logger
from app.db.mongodb import close_db
from app.events.publisher import RabbitPublisher

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ConfigForge — Platform Config Registry",
    version="0.1.0",
    default_response_class=ORJSONResponse,
)
configure_telemetry("config-forge", app=app)  # ADR-058

app.include_router(config_router)


@app.get("/healthz")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.on_event("startup")
async def startup_event():
    # ADR-058 fast-follow: outbound governed events (config-ref resolution). Connect fail-soft — a
    # broker down must not block startup; resolutions just skip the audit publish until it's up.
    publisher = RabbitPublisher(settings.RABBITMQ_URL)
    try:
        await publisher.connect()
    except Exception as exc:  # noqa: BLE001
        logger.warning("config-forge publisher not connected (governance events disabled until broker up): %s", exc)
    app.state.publisher = publisher


@app.on_event("shutdown")
async def shutdown_event():
    publisher = getattr(app.state, "publisher", None)
    if publisher is not None:
        await publisher.close()
    await close_db()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True,
    )
