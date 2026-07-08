# app/main.py
"""App factory + lifespan (Mongo + RabbitMQ + optional auto-seed).

Exposes a module-level ``app`` so the service runs standalone via
``uvicorn app.main:app`` and can later be mounted by the backend.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI

from app.clients.registry_client import ExceptionStoreClient, RegistryClient
from app.config import settings
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.dispatch_repo import DispatchLogRepository
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import (
    ARTIFACT_SCHEMAS,
    CAPABILITIES,
    DISPATCH_LOG,
    HITL_TASKS,
    PROCESS_INSTANCES,
    PROCESS_PACKS,
    MongoClient,
)
from app.engine.engine import ProcessEngine
from app.engine.executor import Executor
from app.events.consumer import DispatchConsumer
from app.events.publisher import RabbitPublisher
from app.events.rabbit import RabbitConnection
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import admin, artifact_schemas, capabilities, health, hitl_tasks, instances, packs
from app.seeding.load import SeedLoader
from app.services.dispatch_service import DispatchService
from app.services.hitl_service import HitlDecisionService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB)
    await mongo.connect()

    rabbit = RabbitConnection(settings.RABBITMQ_URL)
    await rabbit.connect()

    app.state.mongo = mongo
    app.state.rabbit = rabbit
    pack_repo = ProcessPackRepository(mongo.collection(PROCESS_PACKS))
    capability_repo = CapabilityRepository(mongo.collection(CAPABILITIES))
    artifact_schema_repo = ArtifactSchemaRepository(mongo.collection(ARTIFACT_SCHEMAS))
    instance_repo = ProcessInstanceRepository(mongo.collection(PROCESS_INSTANCES))
    hitl_task_repo = HitlTaskRepository(mongo.collection(HITL_TASKS))
    dispatch_repo = DispatchLogRepository(mongo.collection(DISPATCH_LOG))
    app.state.pack_repo = pack_repo
    app.state.capability_repo = capability_repo
    app.state.artifact_schema_repo = artifact_schema_repo
    app.state.instance_repo = instance_repo
    app.state.hitl_task_repo = hitl_task_repo
    app.state.dispatch_repo = dispatch_repo

    if settings.SEED_ON_STARTUP:
        try:
            report = await SeedLoader(settings.SEED_DIR).load(mongo)
            logger.info("Auto-seed: %s", report.as_dict())
        except Exception as exc:  # noqa: BLE001 - never block startup on a seed hiccup
            logger.error("Auto-seed failed: %s", exc)

    # ---- execution wiring (engine + dispatch consumer + HITL service) ----
    http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
    registry_client = RegistryClient(settings.REGISTRY_BASE_URL, http)
    store_client = ExceptionStoreClient(http)
    publisher = RabbitPublisher(settings.RABBITMQ_URL)
    await publisher.connect()

    engine = ProcessEngine(
        registry=registry_client, instance_repo=instance_repo, hitl_repo=hitl_task_repo,
        publisher=publisher, settings=settings, executor=Executor(),
    )
    dispatch_service = DispatchService(
        engine=engine, instance_repo=instance_repo, dispatch_repo=dispatch_repo,
        store_client=store_client, publisher=publisher,
    )
    hitl_service = HitlDecisionService(
        hitl_repo=hitl_task_repo, instance_repo=instance_repo, engine=engine, publisher=publisher,
    )
    app.state.http = http
    app.state.publisher = publisher
    app.state.engine = engine
    app.state.hitl_service = hitl_service

    consumer = DispatchConsumer(
        settings.RABBITMQ_URL, settings.RABBITMQ_DISPATCH_QUEUE, dispatch_service.handle
    )
    consumer_task = asyncio.create_task(consumer.run())
    app.state.dispatch_consumer = consumer

    # Crash-recovery sweep for instances left ``running`` at a checkpoint.
    async def _recover():
        try:
            n = await engine.recover()
            if n:
                logger.info("recovery swept %d running instance(s)", n)
        except Exception as exc:  # noqa: BLE001
            logger.exception("recovery sweep error: %s", exc)
    recover_task = asyncio.create_task(_recover())

    logger.info("agent-runtime ready (simulation=%s)", settings.SIMULATION_MODE)
    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        recover_task.cancel()
        await publisher.close()
        await http.aclose()
        await rabbit.close()
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — Agent Runtime", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    app.include_router(packs.router)
    app.include_router(capabilities.router)
    app.include_router(artifact_schemas.router)
    app.include_router(instances.router)
    app.include_router(hitl_tasks.router)
    app.include_router(admin.router)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
