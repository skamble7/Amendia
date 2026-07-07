# app/main.py
"""App factory + lifespan wiring (Mongo + RabbitMQ).

Exposes a module-level ``app`` so the service runs standalone via
``uvicorn app.main:app`` and can later be mounted as a sub-application by the
backend.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.dal.exceptions_repo import ExceptionRepository
from app.db.mongo import MongoClient
from app.events.rabbit import RabbitPublisher
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import exceptions as exceptions_router
from app.routers import health as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Mongo (+ indexes), then RabbitMQ (+ exchange).
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB, settings.MONGO_COLLECTION)
    await mongo.connect()

    publisher = RabbitPublisher(settings.RABBITMQ_URL)
    await publisher.connect()

    app.state.mongo = mongo
    app.state.repo = ExceptionRepository(mongo.collection)
    app.state.publisher = publisher
    logger.info("stub_exception_generator ready")
    try:
        yield
    finally:
        await publisher.close()
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="Amendia — Stub Exception Generator",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health_router.router)
    app.include_router(exceptions_router.router)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
