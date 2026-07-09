# app/main.py
"""App factory + lifespan (Mongo + optional onboarding seed)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI

from amendia_auth import AuthContext, principal_or_internal

from app.config import auth_settings, settings
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import (
    ARTIFACT_SCHEMAS, BPMN_DOCUMENTS, CAPABILITIES, PACK_RESOLUTIONS,
    PROCESS_PACKS, VALIDATION_REPORTS, MongoClient,
)
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import artifact_schemas, capabilities, health, packs, resolve
from app.services.resolver import ResolveService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB)
    await mongo.connect()

    app.state.mongo = mongo
    app.state.capability_repo = CapabilityRepository(mongo.collection(CAPABILITIES))
    app.state.artifact_schema_repo = ArtifactSchemaRepository(mongo.collection(ARTIFACT_SCHEMAS))
    app.state.pack_repo = ProcessPackRepository(
        mongo.collection(PROCESS_PACKS),
        mongo.collection(VALIDATION_REPORTS),
        mongo.collection(PACK_RESOLUTIONS),
    )
    app.state.bpmn_repo = BpmnRepository(mongo.collection(BPMN_DOCUMENTS))
    app.state.resolver = ResolveService(app.state.pack_repo, settings.RESOLVE_CACHE_TTL)
    app.state.auth = AuthContext(auth_settings)

    if settings.SEED_ON_STARTUP:
        try:
            from app.seeding.onboard_seed import onboard
            report = await onboard(
                settings.SEED_DIR,
                app.state.capability_repo, app.state.artifact_schema_repo,
                app.state.pack_repo, app.state.bpmn_repo,
            )
            logger.info("Onboarding seed: %s", report)
        except Exception as exc:  # noqa: BLE001 - never block startup on a seed hiccup
            logger.error("Onboarding seed failed: %s", exc)

    logger.info("process-registry ready")
    try:
        yield
    finally:
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — Process Registry", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    if settings.ENABLE_DEV_CORS:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    # Baseline: reads require a principal OR the shared internal token (the runtime
    # reads packs/capabilities/schemas and the ingestor calls /resolve service-to-
    # service). Mutations additionally require role.process.owner (guarded per-route
    # in the routers).
    guarded = [Depends(principal_or_internal)]
    app.include_router(health.router)
    app.include_router(capabilities.router, dependencies=guarded)
    app.include_router(artifact_schemas.router, dependencies=guarded)
    app.include_router(packs.router, dependencies=guarded)
    app.include_router(resolve.router, dependencies=guarded)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
