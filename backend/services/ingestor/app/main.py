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
from fastapi import FastAPI

from app.clients.stub_client import StubClient
from app.config import settings
from app.dal.ingestion_repo import IngestionRepository
from app.db.mongo import MongoClient
from app.events.rabbit import RabbitConsumer
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import health as health_router
from app.routers import ingestions as ingestions_router
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Mongo (+ indexes).
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB, settings.MONGO_COLLECTION)
    await mongo.connect()

    # HTTP client → the exception store (stub).
    http = httpx.AsyncClient(timeout=15)
    stub_client = StubClient(settings.STUB_BASE_URL, http)

    repo = IngestionRepository(mongo.collection)
    service = IngestionService(repo, stub_client)

    # RabbitMQ consumer as a background task.
    consumer = RabbitConsumer(settings.RABBITMQ_URL, settings.RABBITMQ_QUEUE, service.handle_event)
    consumer_task = asyncio.create_task(consumer.run())

    app.state.mongo = mongo
    app.state.repo = repo
    app.state.consumer = consumer
    app.state.http = http
    logger.info("ingestor ready")
    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        await http.aclose()
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — Ingestor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health_router.router)
    app.include_router(ingestions_router.router)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
