# app/main.py
"""App factory + lifespan.

Wires the RabbitMQ broadcast consumer → fan-out hub, and mounts the SSE stream.
The consumer callback maps each event to a thin signal and publishes it to the hub;
the ``/stream`` endpoint drains a per-client queue. Auth: this is a downstream
service, so ``AuthContext(auth_settings)`` resolves principals over HTTP against the
identity service by default — though the stream only needs bearer validation.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from amendia_auth import AuthContext

from app.config import auth_settings, settings
from app.events.consumer import BroadcastConsumer
from app.events.signal_mapper import to_signal
from app.hub import NotificationHub
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import health, stream

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub = NotificationHub(client_queue_maxsize=settings.CLIENT_QUEUE_MAXSIZE)

    async def handle(payload: dict, routing_key: str) -> None:
        signal = to_signal(payload, routing_key)
        if signal is not None:
            hub.publish(signal)

    consumer = BroadcastConsumer(settings.RABBITMQ_URL, handle)

    app.state.hub = hub
    app.state.consumer = consumer
    app.state.auth = AuthContext(auth_settings)

    consumer_task = asyncio.create_task(consumer.run())
    logger.info("notification-service ready")
    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — Notifications", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    if settings.ENABLE_DEV_CORS:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(stream.router)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
