# app/main.py
"""App factory + lifespan wiring (Mongo + RabbitMQ).

Exposes a module-level ``app`` so the service runs standalone via ``uvicorn app.main:app``. ADR-059: one
domain-blind ``trigger_messages`` store (was exceptions + tickets), served by a neutral ``/triggers`` +
``/generators`` surface.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI

from amendia_auth import AuthContext, principal_or_internal

from app.config import auth_settings, settings
from app.dal.trigger_repo import TriggerRepository
from app.db.mongo import MongoClient
from app.events.rabbit import RabbitPublisher
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import generators as generators_router
from app.routers import health as health_router
from app.routers import triggers as triggers_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Mongo (+ the single trigger_messages index), then RabbitMQ (+ exchange).
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB, settings.MONGO_COLLECTION)
    await mongo.connect()

    publisher = RabbitPublisher(settings.RABBITMQ_URL)
    await publisher.connect()

    app.state.mongo = mongo
    app.state.repo = TriggerRepository(mongo.collection)
    app.state.publisher = publisher
    app.state.auth = AuthContext(auth_settings)
    logger.info("stub_trigger_generator ready")
    try:
        yield
    finally:
        await publisher.close()
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="Amendia — Stub Trigger Generator",
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
    # Generate requires an authenticated principal; the fetch-back reads are also called
    # service-to-service (runtime/ingestor), so accept the internal token too. Under compat-stub,
    # endpoints are exempt when no bearer is present.
    app.include_router(triggers_router.router, dependencies=[Depends(principal_or_internal)])
    # Domain-neutral discovery + generation: the UI reads this catalog to offer trigger sources.
    app.include_router(generators_router.router, dependencies=[Depends(principal_or_internal)])
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
