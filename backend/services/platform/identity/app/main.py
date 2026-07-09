# app/main.py
"""App factory + lifespan (Mongo + auth context + optional role-assignment seed)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from amendia_auth import AuthContext

from app.config import auth_settings, settings
from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository
from app.db.mongo import (
    PENDING_ROLE_ASSIGNMENTS,
    ROLE_ASSIGNMENTS,
    USERS,
    MongoClient,
)
from app.deps import get_mongo
from app.logging_conf import configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.routers import admin, health, internal, me, pending
from app.services.resolver import LocalResolver, ResolveService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoClient(settings.MONGO_URI, settings.MONGO_DB)
    await mongo.connect()

    user_repo = UserRepository(mongo.collection(USERS))
    role_repo = RoleRepository(
        mongo.collection(ROLE_ASSIGNMENTS), mongo.collection(PENDING_ROLE_ASSIGNMENTS)
    )
    resolve_service = ResolveService(
        user_repo, role_repo, jit_default_status=settings.JIT_DEFAULT_STATUS
    )

    app.state.mongo = mongo
    app.state.user_repo = user_repo
    app.state.role_repo = role_repo
    app.state.resolve_service = resolve_service
    # Identity consumes amendia_auth too, but resolves locally (no self-HTTP).
    app.state.auth = AuthContext(auth_settings, resolver=LocalResolver(resolve_service))

    if settings.SEED_ON_STARTUP:
        try:
            from app.seeding.seed import seed_role_assignments
            report = await seed_role_assignments(role_repo)
            logger.info("identity seed: %s", report)
        except Exception as exc:  # noqa: BLE001 - never block startup on a seed hiccup
            logger.error("identity seed failed: %s", exc)

    logger.info("identity service ready")
    try:
        yield
    finally:
        await mongo.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="Amendia — Identity", version="0.1.0", lifespan=lifespan)
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
    app.include_router(internal.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(pending.router)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
