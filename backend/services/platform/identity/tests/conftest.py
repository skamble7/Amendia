# tests/conftest.py
"""Fixtures: in-memory Mongo (mongomock-motor), identity repos + resolve service,
and an httpx client with repos wired and ``current_user`` overridable per test."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from amendia_auth import AuthContext, AuthenticatedUser, Principal, current_user
from amendia_auth.settings import AuthSettings

from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository
from app.db.mongo import (
    PENDING_ROLE_ASSIGNMENTS,
    ROLE_ASSIGNMENTS,
    USERS,
    create_indexes,
)
from app.deps import get_mongo, get_role_repo, get_resolve_service, get_user_repo
from app.main import create_app
from app.services.resolver import LocalResolver, ResolveService

INTERNAL_TOKEN = "test-internal"


class FakeMongo:
    def __init__(self, db):
        self._db = db

    def collection(self, name):
        return self._db[name]

    async def ping(self):
        return True


class UserHolder:
    """Lets a test choose which AuthenticatedUser ``current_user`` yields."""

    def __init__(self):
        self.user = None


def make_user(user_id="usr-priya", roles=("role.platform.admin", "role.process.owner")):
    return AuthenticatedUser(
        amendia_user_id=user_id,
        email=f"{user_id}@amendia.dev",
        display_name=user_id,
        roles=set(roles),
        principal=Principal(iss="test", sub=user_id),
    )


@pytest_asyncio.fixture
async def db():
    d = AsyncMongoMockClient()["identity_test"]
    await create_indexes(d)
    return d


@pytest.fixture
def user_repo(db):
    return UserRepository(db[USERS])


@pytest.fixture
def role_repo(db):
    return RoleRepository(db[ROLE_ASSIGNMENTS], db[PENDING_ROLE_ASSIGNMENTS])


@pytest.fixture
def resolve_service(user_repo, role_repo):
    return ResolveService(user_repo, role_repo, jit_default_status="active")


@pytest.fixture
def holder():
    h = UserHolder()
    h.user = make_user()  # default caller is a platform admin
    return h


@pytest_asyncio.fixture
async def client(db, user_repo, role_repo, resolve_service, holder):
    app = create_app()
    auth_settings = AuthSettings(internal_token=INTERNAL_TOKEN)
    app.state.auth = AuthContext(auth_settings, resolver=LocalResolver(resolve_service))
    app.dependency_overrides[get_mongo] = lambda: FakeMongo(db)
    app.dependency_overrides[get_user_repo] = lambda: user_repo
    app.dependency_overrides[get_role_repo] = lambda: role_repo
    app.dependency_overrides[get_resolve_service] = lambda: resolve_service
    app.dependency_overrides[current_user] = lambda: holder.user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
