# tests/conftest.py
"""Fixtures: an in-memory Mongo (mongomock-motor) with real indexes, repositories
built on it, and an httpx client with the FastAPI deps overridden."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

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
    create_indexes,
)
from app.deps import (
    get_artifact_schema_repo,
    get_capability_repo,
    get_dispatch_repo,
    get_hitl_task_repo,
    get_instance_repo,
    get_mongo,
    get_pack_repo,
    get_rabbit,
)
from app.main import create_app
from app.seeding.load import SeedLoader


class FakeMongo:
    """Adapter matching the MongoClient surface the seed loader/health use."""

    def __init__(self, db) -> None:
        self._db = db

    def collection(self, name: str):
        return self._db[name]

    async def ping(self) -> bool:
        return True


class FakeRabbit:
    is_ready = True


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    d = client["amendia_test"]
    await create_indexes(d)
    return d


@pytest.fixture
def mongo(db) -> FakeMongo:
    return FakeMongo(db)


@pytest.fixture
def pack_repo(db) -> ProcessPackRepository:
    return ProcessPackRepository(db[PROCESS_PACKS])


@pytest.fixture
def capability_repo(db) -> CapabilityRepository:
    return CapabilityRepository(db[CAPABILITIES])


@pytest.fixture
def artifact_schema_repo(db) -> ArtifactSchemaRepository:
    return ArtifactSchemaRepository(db[ARTIFACT_SCHEMAS])


@pytest.fixture
def instance_repo(db) -> ProcessInstanceRepository:
    return ProcessInstanceRepository(db[PROCESS_INSTANCES])


@pytest.fixture
def hitl_task_repo(db) -> HitlTaskRepository:
    return HitlTaskRepository(db[HITL_TASKS])


@pytest.fixture
def dispatch_repo(db) -> DispatchLogRepository:
    return DispatchLogRepository(db[DISPATCH_LOG])


@pytest_asyncio.fixture
async def seeded(mongo):
    """Load the real seed dataset into the in-memory db."""
    return await SeedLoader(settings.SEED_DIR).load(mongo)


@pytest.fixture
def bundle():
    """The wire-repair pack bundle built straight from the seed dir (no Mongo)."""
    from app.engine.bundle import PackBundle
    return PackBundle.from_seed_dir(settings.SEED_DIR)


@pytest_asyncio.fixture
async def client(mongo, pack_repo, capability_repo, artifact_schema_repo, instance_repo, hitl_task_repo, dispatch_repo):
    app = create_app()
    app.dependency_overrides[get_mongo] = lambda: mongo
    app.dependency_overrides[get_rabbit] = lambda: FakeRabbit()
    app.dependency_overrides[get_pack_repo] = lambda: pack_repo
    app.dependency_overrides[get_capability_repo] = lambda: capability_repo
    app.dependency_overrides[get_artifact_schema_repo] = lambda: artifact_schema_repo
    app.dependency_overrides[get_instance_repo] = lambda: instance_repo
    app.dependency_overrides[get_hitl_task_repo] = lambda: hitl_task_repo
    app.dependency_overrides[get_dispatch_repo] = lambda: dispatch_repo
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
