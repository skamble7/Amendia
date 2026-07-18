# app/deps.py
"""FastAPI dependency providers — repositories/services live on app.state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import Request

from app.config import settings
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.onboarding_repo import OnboardingRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import MongoClient
from app.services.onboarding import OnboardingService
from app.services.resolver import ResolveService
from app.validation.pack_validator import PackValidator


def load_sample_envelopes() -> List[dict]:
    d = Path(settings.SEED_DIR) / "sample-exception"
    if not d.exists():
        return []
    return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]


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
    return PackValidator(request.app.state.capability_repo, request.app.state.artifact_schema_repo,
                         profile=settings.EXECUTION_PROFILE)


def get_resolver(request: Request) -> ResolveService:
    return request.app.state.resolver


def get_onboarding_repo(request: Request) -> OnboardingRepository:
    return request.app.state.onboarding_repo


def get_onboarding_service(request: Request) -> OnboardingService:
    st = request.app.state
    return OnboardingService(
        st.onboarding_repo, st.capability_repo, st.artifact_schema_repo,
        st.pack_repo, st.bpmn_repo, st.mcp_introspector,
        sample_envelopes=load_sample_envelopes(),
        profile=settings.EXECUTION_PROFILE,
    )
