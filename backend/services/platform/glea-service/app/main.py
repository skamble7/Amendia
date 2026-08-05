# app/main.py
"""glea-service — the GLEA audit system-of-record (ADR-058 Phase B).

Consumes governed events off ``amendia.events`` on a durable named queue and persists them append-only
into ClickHouse ``audit_events`` (the sole writer), and serves the per-instance audit read API. Bootstrap
is fail-soft: neither RabbitMQ nor ClickHouse being down at startup crashes the process — the consumer
retries the broker, and the ClickHouse client connects lazily + self-heals (events requeue meanwhile).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from amendia_telemetry import configure_telemetry

from app.clickhouse.client import StorageUnavailable
from app.clickhouse.provider import ClickHouseProvider
from app.clickhouse.reader import AuditReader
from app.clickhouse.writer import AuditWriter
from app.config import settings
from app.events.consumer import AuditConsumer
from app.events.mapper import to_row
from app.logging_conf import configure_logging
from app.routers import audit, health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = ClickHouseProvider()
    writer = AuditWriter(provider)
    reader = AuditReader(provider)

    async def handle(routing_key: str, payload: dict) -> None:
        # to_row → UnmappableEvent (poison, dropped by the consumer); insert → StorageUnavailable
        # (requeued by the consumer). glea is the sole writer of audit_events.
        row = to_row(routing_key, payload)
        await writer.insert(row)

    consumer = AuditConsumer(settings.RABBITMQ_URL, handle)
    app.state.provider = provider
    app.state.writer = writer
    app.state.reader = reader
    app.state.consumer = consumer

    # Best-effort early schema bootstrap; if ClickHouse is down it self-heals on the first event.
    try:
        await provider.ensure()
    except StorageUnavailable as exc:
        logger.warning("clickhouse not ready at startup (will connect on first event): %s", exc)

    consumer_task = asyncio.create_task(consumer.run())
    logger.info("glea-service ready")
    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        provider.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — GLEA audit", version="0.1.0", lifespan=lifespan)
    configure_telemetry("glea-service", app=app)  # ADR-058
    if settings.ENABLE_DEV_CORS:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(health.router)
    app.include_router(audit.router)
    return app


app = create_app()
