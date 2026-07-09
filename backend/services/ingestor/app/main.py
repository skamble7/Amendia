# app/main.py
"""App factory + lifespan wiring (Mongo + HTTP client + RabbitMQ consumer).

Exposes a module-level ``app`` so the service runs standalone via
``uvicorn app.main:app`` and can later be mounted as a sub-application by the
backend.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import Depends, FastAPI

from amendia_auth import AuthContext, current_principal

from app.clients.registry_client import RegistryClient
from app.clients.stub_client import StubClient
from app.config import auth_settings, settings
from app.dal.ingestion_repo import IngestionRepository
from app.db.mongo import MongoClient
from app.events.publisher import RabbitPublisher
from app.events.rabbit import RabbitConsumer
from app.events.reply_consumer import ReplyConsumer
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import health as health_router
from app.routers import ingestions as ingestions_router
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


async def _resolve_sweep(service: IngestionService, interval: int) -> None:
    """Periodically re-resolve records stuck in ``received`` (registry was down)."""
    while True:
        await asyncio.sleep(interval)
        try:
            await service.resolve_pending()
        except Exception as exc:  # noqa: BLE001
            logger.exception("resolve sweep error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Mongo (+ indexes).
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB, settings.MONGO_COLLECTION)
    await mongo.connect()

    # HTTP client → the exception store (stub) + process registry.
    http = httpx.AsyncClient(timeout=15)
    stub_client = StubClient(settings.STUB_BASE_URL, http, internal_token=auth_settings.internal_token)
    registry_client = RegistryClient(
        settings.REGISTRY_BASE_URL, http, internal_token=auth_settings.internal_token
    )

    # Outbound event publisher (exception_dispatched).
    publisher = RabbitPublisher(settings.RABBITMQ_URL)
    await publisher.connect()

    repo = IngestionRepository(mongo.collection)
    service = IngestionService(repo, stub_client, registry_client, publisher)

    # RabbitMQ consumers as background tasks: inbound events + dispatch replies.
    consumer = RabbitConsumer(settings.RABBITMQ_URL, settings.RABBITMQ_QUEUE, service.handle_event)
    consumer_task = asyncio.create_task(consumer.run())
    reply_consumer = ReplyConsumer(
        settings.RABBITMQ_URL, settings.RABBITMQ_REPLY_QUEUE, service.handle_reply
    )
    reply_task = asyncio.create_task(reply_consumer.run())

    # Retry sweep for records the registry couldn't resolve yet.
    sweep_task = asyncio.create_task(_resolve_sweep(service, settings.RESOLVE_RETRY_SECONDS))

    app.state.mongo = mongo
    app.state.repo = repo
    app.state.auth = AuthContext(auth_settings)
    app.state.consumer = consumer
    app.state.reply_consumer = reply_consumer
    app.state.publisher = publisher
    app.state.http = http
    logger.info("ingestor ready")
    try:
        yield
    finally:
        await consumer.stop()
        await reply_consumer.stop()
        consumer_task.cancel()
        reply_task.cancel()
        sweep_task.cancel()
        await publisher.close()
        await http.aclose()
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — Ingestor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    if settings.ENABLE_DEV_CORS:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health_router.router)
    # Baseline: reads require an authenticated principal. /health stays open.
    app.include_router(ingestions_router.router, dependencies=[Depends(current_principal)])
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
