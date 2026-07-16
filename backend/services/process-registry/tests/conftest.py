# tests/conftest.py
"""Fixtures: in-memory Mongo (mongomock-motor) + registry repos + httpx client with
DI-overridden dependencies, plus seed-file loaders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from app.config import settings
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.onboarding_repo import OnboardingRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import (
    ARTIFACT_SCHEMAS, BPMN_DOCUMENTS, CAPABILITIES, ONBOARDING_SESSIONS,
    PACK_RESOLUTIONS, PROCESS_PACKS, VALIDATION_REPORTS, create_indexes,
)
from app.deps import (
    get_artifact_schema_repo, get_bpmn_repo, get_capability_repo, get_mongo,
    get_onboarding_service, get_pack_repo, get_resolver, get_validator,
)
from app.main import create_app
from app.services.mcp_introspect import RawMcpTool
from app.services.onboarding import OnboardingService
from app.services.resolver import ResolveService
from app.validation.pack_validator import PackValidator


# --------------------------------------------------------------------------- #
# In-memory MCP introspection (no live network in CI).
# --------------------------------------------------------------------------- #

class FakeMcpIntrospector:
    def __init__(self, tools):
        self._tools = tools

    async def list_tools(self, *, endpoint, transport, headers):
        return list(self._tools)


def default_fake_tools():
    return [
        RawMcpTool(
            name="screen_party", description="Screen a party against sanctions.",
            input_schema={"type": "object", "properties": {"party": {"type": "string"}}, "required": ["party"]},
            output_schema={"type": "object", "properties": {"hit": {"type": "boolean"}}, "required": ["hit"]},
        ),
        RawMcpTool(  # non-compliant: no outputSchema
            name="notify_ops", description="Notify the ops channel.",
            input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
            output_schema=None,
        ),
    ]


# A minimal, valid single-serviceTask BPMN used across onboarding tests.
MCP_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="def_1" targetNamespace="http://amendia">
  <bpmn:process id="mcp_test_process" isExecutable="true">
    <bpmn:startEvent id="Start_1"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Task_Screen" name="Screen party"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="End_1"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Task_Screen"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Screen" targetRef="End_1"/>
  </bpmn:process>
</bpmn:definitions>
"""

SEED = Path(settings.SEED_DIR)


def load_schemas() -> List[ArtifactSchemaRegistration]:
    return [ArtifactSchemaRegistration.model_validate_json(f.read_text())
            for f in sorted((SEED / "artifact-schemas").glob("*.json"))]


def load_capabilities() -> List[CapabilityDescriptor]:
    return [CapabilityDescriptor.model_validate_json(f.read_text())
            for f in sorted((SEED / "capabilities").glob("*.json"))]


def load_manifest() -> ProcessPackManifest:
    return ProcessPackManifest.model_validate_json((SEED / "manifest.json").read_text())


def load_bpmn() -> str:
    return (SEED / "wire-repair.bpmn").read_text()


def load_sample() -> dict:
    return json.loads((SEED / "sample-exception" / "wire-exception-ac01.json").read_text())


class FakeMongo:
    def __init__(self, db):
        self._db = db

    def collection(self, name):
        return self._db[name]

    async def ping(self):
        return True


@pytest_asyncio.fixture
async def db():
    d = AsyncMongoMockClient()["amendia_test"]
    await create_indexes(d)
    return d


@pytest.fixture
def cap_repo(db):
    return CapabilityRepository(db[CAPABILITIES])


@pytest.fixture
def schema_repo(db):
    return ArtifactSchemaRepository(db[ARTIFACT_SCHEMAS])


@pytest.fixture
def pack_repo(db):
    return ProcessPackRepository(db[PROCESS_PACKS], db[VALIDATION_REPORTS], db[PACK_RESOLUTIONS])


@pytest.fixture
def bpmn_repo(db):
    return BpmnRepository(db[BPMN_DOCUMENTS])


@pytest.fixture
def validator(cap_repo, schema_repo):
    return PackValidator(cap_repo, schema_repo)


@pytest.fixture
def resolver(pack_repo):
    return ResolveService(pack_repo, ttl_seconds=0.0)  # no caching in tests


@pytest.fixture
def onboarding_repo(db):
    return OnboardingRepository(db[ONBOARDING_SESSIONS])


@pytest.fixture
def fake_introspector():
    return FakeMcpIntrospector(default_fake_tools())


@pytest.fixture
def onboarding_service(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(
        onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
        fake_introspector, sample_envelopes=[load_sample()],
    )


@pytest_asyncio.fixture
async def registered(cap_repo, schema_repo):
    """All seed capabilities + artifact schemas registered (no pack)."""
    from app.services.registration import register_schema
    for reg in load_schemas():
        await register_schema(reg, schema_repo)
    for cap in load_capabilities():
        await cap_repo.insert(cap)


@pytest_asyncio.fixture
async def onboarded(cap_repo, schema_repo, pack_repo, bpmn_repo):
    """Full seed onboarded to active via the real pipeline."""
    from app.seeding.onboard_seed import onboard
    return await onboard(SEED, cap_repo, schema_repo, pack_repo, bpmn_repo)


@pytest_asyncio.fixture
async def client(db, cap_repo, schema_repo, pack_repo, bpmn_repo, resolver, onboarding_service):
    from amendia_auth import AuthContext
    from amendia_auth.settings import AuthSettings

    app = create_app()
    # Auth isn't the subject of these suites: a synthetic user with all seeded roles.
    app.state.auth = AuthContext(AuthSettings(auth_disabled=True, internal_token="test-internal"))
    app.dependency_overrides[get_mongo] = lambda: FakeMongo(db)
    app.dependency_overrides[get_capability_repo] = lambda: cap_repo
    app.dependency_overrides[get_artifact_schema_repo] = lambda: schema_repo
    app.dependency_overrides[get_pack_repo] = lambda: pack_repo
    app.dependency_overrides[get_bpmn_repo] = lambda: bpmn_repo
    app.dependency_overrides[get_resolver] = lambda: resolver
    app.dependency_overrides[get_validator] = lambda: PackValidator(cap_repo, schema_repo)
    app.dependency_overrides[get_onboarding_service] = lambda: onboarding_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
