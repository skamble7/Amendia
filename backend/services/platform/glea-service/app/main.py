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
from app.clickhouse.provider import ClickHousePool
from app.clickhouse.reader import AuditReader, CohortReader
from app.clickhouse.sealer import AuditSealer
from app.clickhouse.writer import AuditWriter, CohortSlaWriter, CohortWriter
from app.config import settings
from app.events.consumer import AuditConsumer
from app.events.mapper import (
    is_cohort_event, is_cohort_sla_event, to_cohort_row, to_cohort_sla_row, to_row,
)
from app.logging_conf import configure_logging
from app.routers import audit, cohorts, health

logger = logging.getLogger(__name__)


async def _sealer_loop(sealer: AuditSealer, stop: asyncio.Event) -> None:
    """Periodic tamper-evidence sealing pass. Fail-soft: ClickHouse down → retry next tick."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.SEALING_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            break
        try:
            await sealer.seal_quiescent(settings.SEALING_QUIESCENT_SECONDS)
        except StorageUnavailable as exc:
            logger.debug("sealing pass skipped (clickhouse unavailable): %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sealing pass error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = ClickHousePool()
    writer = AuditWriter(pool)
    reader = AuditReader(pool)
    cohort_writer = CohortWriter(pool)          # ADR-063 Phase 3A
    cohort_sla_writer = CohortSlaWriter(pool)   # ADR-064 P3
    cohort_reader = CohortReader(pool)

    async def handle(routing_key: str, payload: dict) -> None:
        # Branch by routing key: cohort-SLA → cohort_sla_events; cohort lifecycle → cohort_events; everything
        # else → audit_events (each its own table). to_*_row → UnmappableEvent (poison, dropped by the
        # consumer); insert → StorageUnavailable (requeued — none of these are dropped on a ClickHouse blip).
        if is_cohort_sla_event(routing_key):
            await cohort_sla_writer.insert(to_cohort_sla_row(routing_key, payload))
        elif is_cohort_event(routing_key):
            await cohort_writer.insert(to_cohort_row(routing_key, payload))
        else:
            await writer.insert(to_row(routing_key, payload))

    consumer = AuditConsumer(settings.RABBITMQ_URL, handle)
    sealer = AuditSealer(reader, writer)
    app.state.pool = pool
    app.state.writer = writer
    app.state.reader = reader
    app.state.cohort_writer = cohort_writer
    app.state.cohort_sla_writer = cohort_sla_writer
    app.state.cohort_reader = cohort_reader
    app.state.consumer = consumer
    app.state.sealer = sealer

    # Best-effort early schema bootstrap; if ClickHouse is down it self-heals on the first event.
    try:
        await asyncio.to_thread(pool.warm)
    except StorageUnavailable as exc:
        logger.warning("clickhouse not ready at startup (will connect on first event): %s", exc)

    consumer_task = asyncio.create_task(consumer.run())
    seal_stop = asyncio.Event()
    seal_task = (
        asyncio.create_task(_sealer_loop(sealer, seal_stop)) if settings.SEALING_ENABLED else None
    )
    logger.info("glea-service ready")
    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        seal_stop.set()
        for task in (consumer_task, seal_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        pool.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — GLEA audit", version="0.1.0", lifespan=lifespan)
    configure_telemetry("glea-service", app=app)  # ADR-058
    if settings.ENABLE_DEV_CORS:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(health.router)
    app.include_router(audit.router)
    app.include_router(cohorts.router)  # ADR-063 Phase 3A cohort read APIs
    return app


app = create_app()
