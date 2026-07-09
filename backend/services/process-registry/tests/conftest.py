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
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import (
    ARTIFACT_SCHEMAS, BPMN_DOCUMENTS, CAPABILITIES, PACK_RESOLUTIONS,
    PROCESS_PACKS, VALIDATION_REPORTS, create_indexes,
)
from app.deps import (
    get_artifact_schema_repo, get_bpmn_repo, get_capability_repo, get_mongo,
    get_pack_repo, get_resolver, get_validator,
)
from app.main import create_app
from app.services.resolver import ResolveService
from app.validation.pack_validator import PackValidator

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
async def client(db, cap_repo, schema_repo, pack_repo, bpmn_repo, resolver):
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
