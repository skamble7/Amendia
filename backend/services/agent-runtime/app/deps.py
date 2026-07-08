# app/deps.py
"""FastAPI dependency providers — everything lives on app.state (set in lifespan)."""
from __future__ import annotations

from fastapi import Request

from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.dispatch_repo import DispatchLogRepository
from app.dal.hitl_task_repo import HitlTaskRepository
from app.dal.instance_repo import ProcessInstanceRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import MongoClient
from app.events.rabbit import RabbitConnection


def get_mongo(request: Request) -> MongoClient:
    return request.app.state.mongo


def get_rabbit(request: Request) -> RabbitConnection:
    return request.app.state.rabbit


def get_pack_repo(request: Request) -> ProcessPackRepository:
    return request.app.state.pack_repo


def get_capability_repo(request: Request) -> CapabilityRepository:
    return request.app.state.capability_repo


def get_artifact_schema_repo(request: Request) -> ArtifactSchemaRepository:
    return request.app.state.artifact_schema_repo


def get_instance_repo(request: Request) -> ProcessInstanceRepository:
    return request.app.state.instance_repo


def get_hitl_task_repo(request: Request) -> HitlTaskRepository:
    return request.app.state.hitl_task_repo


def get_dispatch_repo(request: Request) -> DispatchLogRepository:
    return request.app.state.dispatch_repo


def get_engine(request: Request):
    """The ProcessEngine (present only when execution wiring is up)."""
    return getattr(request.app.state, "engine", None)


def get_hitl_service(request: Request):
    svc = getattr(request.app.state, "hitl_service", None)
    if svc is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="HITL decision service not available")
    return svc
