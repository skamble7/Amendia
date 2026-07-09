# tests/test_resolve.py
"""ResolveService: JIT creation, repeat-resolve stability, email reconcile,
pending-role materialisation, and clean handling of a unique-index race."""
from __future__ import annotations

import pytest

from app.dal.base import DuplicateError


async def test_jit_creates_user_once(resolve_service, user_repo):
    r1 = await resolve_service.resolve(iss="kc", sub="s1", email="a@x.dev", name="A")
    assert r1.amendia_user_id.startswith("usr-")
    assert r1.status == "active"
    r2 = await resolve_service.resolve(iss="kc", sub="s1", email="a@x.dev", name="A")
    assert r2.amendia_user_id == r1.amendia_user_id  # same user on repeat


async def test_email_and_name_reconciled(resolve_service, user_repo):
    r1 = await resolve_service.resolve(iss="kc", sub="s2", email="old@x.dev", name="Old")
    await resolve_service.resolve(iss="kc", sub="s2", email="new@x.dev", name="New")
    stored = await user_repo.get(r1.amendia_user_id)
    assert stored.email == "new@x.dev"
    assert stored.display_name == "New"


async def test_pending_roles_materialised_on_first_login(resolve_service, role_repo):
    await role_repo.add_pending("riya@amendia.dev", "role.payments.ops_analyst", "seed")
    resolved = await resolve_service.resolve(
        iss="kc", sub="riya-sub", email="riya@amendia.dev", name="Riya"
    )
    assert resolved.roles == ["role.payments.ops_analyst"]
    # Idempotent: a second login does not duplicate the grant.
    again = await resolve_service.resolve(iss="kc", sub="riya-sub", email="riya@amendia.dev")
    assert again.roles == ["role.payments.ops_analyst"]


async def test_pending_roles_case_insensitive_email(resolve_service, role_repo):
    await role_repo.add_pending("Priya@Amendia.Dev", "role.platform.admin", "seed")
    resolved = await resolve_service.resolve(iss="kc", sub="p", email="priya@amendia.dev")
    assert "role.platform.admin" in resolved.roles


async def test_identity_race_surfaces_then_retries(user_repo, resolve_service):
    # Reproduce the lost-race sequence inside _provision: this request sees no user
    # (get_by_identity → None), attempts insert, hits the unique index (DuplicateError),
    # then recovers by re-fetching the user the concurrent writer created.
    # (The real unique index enforces this; mongomock-motor doesn't honour a
    # multikey unique index, so we drive the exact sequence directly.)
    winner = await user_repo.insert(
        iss="kc", sub="dup", email="d@x.dev", display_name="D", status="active"
    )

    calls = {"n": 0}
    real_get = user_repo.get_by_identity

    async def _get_by_identity(iss, sub):
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_get(iss, sub)

    async def _raise(**_kwargs):
        raise DuplicateError("identity kc/dup")

    user_repo.get_by_identity = _get_by_identity  # type: ignore[method-assign]
    user_repo.insert = _raise  # type: ignore[method-assign]

    resolved = await resolve_service.resolve(iss="kc", sub="dup", email="d@x.dev")
    assert resolved.amendia_user_id == winner.amendia_user_id
