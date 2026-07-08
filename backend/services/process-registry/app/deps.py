# app/deps.py
"""FastAPI dependency providers — repositories/services live on app.state."""
from __future__ import annotations

from fastapi import Request

from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import MongoClient
from app.services.resolver import ResolveService
from app.validation.pack_validator import PackValidator


def get_mongo(request: Request) -> MongoClient:
    return request.app.state.mongo


def get_capability_repo(request: Request) -> CapabilityRepository:
    return request.app.state.capability_repo


def get_artifact_schema_repo(request: Request) -> ArtifactSchemaRepository:
    return request.app.state.artifact_schema_repo


def get_pack_repo(request: Request) -> ProcessPackRepository:
    return request.app.state.pack_repo


def get_bpmn_repo(request: Request) -> BpmnRepository:
    return request.app.state.bpmn_repo


def get_validator(request: Request) -> PackValidator:
    return PackValidator(request.app.state.capability_repo, request.app.state.artifact_schema_repo)


def get_resolver(request: Request) -> ResolveService:
    return request.app.state.resolver
