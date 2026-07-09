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
from fastapi import Depends, FastAPI

from amendia_auth import AuthContext, principal_or_internal

from app.config import auth_settings, settings
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
    app.state.auth = AuthContext(auth_settings)
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
    if settings.ENABLE_DEV_CORS:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health_router.router)
    # Baseline: generate requires an authenticated principal; the fetch-back reads
    # are also called service-to-service (runtime/ingestor), so accept the internal
    # token too. Under compat-stub, endpoints are exempt when no bearer is present.
    app.include_router(exceptions_router.router, dependencies=[Depends(principal_or_internal)])
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
