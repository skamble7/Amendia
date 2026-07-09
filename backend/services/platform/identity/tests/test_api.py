# tests/test_api.py
"""HTTP surface: /me, internal resolve (token guard), admin guards + role CRUD,
disable/enable, and seed idempotency."""
from __future__ import annotations

import pytest

from .conftest import INTERNAL_TOKEN, make_user


# ----------------------------- /me ------------------------------------------ #
async def test_me_returns_caller(client, resolve_service, holder):
    resolved = await resolve_service.resolve(iss="kc", sub="me-sub", email="me@x.dev", name="Me")
    holder.user = make_user(user_id=resolved.amendia_user_id, roles=("role.process.owner",))
    r = await client.get("/me")
    assert r.status_code == 200
    body = r.json()
    assert body["amendia_user_id"] == resolved.amendia_user_id
    assert body["roles"] == ["role.process.owner"]


# ---------------------- internal resolve-principal -------------------------- #
async def test_internal_resolve_requires_token(client):
    r = await client.post("/internal/resolve-principal", json={"iss": "kc", "sub": "x"})
    assert r.status_code == 401


async def test_internal_resolve_jit(client):
    r = await client.post(
        "/internal/resolve-principal",
        json={"iss": "kc", "sub": "new-user", "email": "n@x.dev", "name": "N"},
        headers={"X-Amendia-Internal": INTERNAL_TOKEN},
    )
    assert r.status_code == 200
    assert r.json()["amendia_user_id"].startswith("usr-")
    assert r.json()["status"] == "active"


# ------------------------------ admin --------------------------------------- #
async def test_admin_guard_forbids_non_admin(client, resolve_service, holder):
    await resolve_service.resolve(iss="kc", sub="m", email="m@x.dev")
    holder.user = make_user(user_id="usr-marcus", roles=("role.payments.ops_approver",))
    r = await client.get("/users")
    assert r.status_code == 403
    assert r.json()["detail"]["missing_role"] == "role.platform.admin"


async def test_admin_list_and_role_crud(client, resolve_service, holder):
    resolved = await resolve_service.resolve(iss="kc", sub="u1", email="u1@x.dev", name="U1")
    uid = resolved.amendia_user_id

    listed = await client.get("/users")
    assert listed.status_code == 200
    assert any(u["amendia_user_id"] == uid for u in listed.json())

    # assign
    r = await client.post(f"/users/{uid}/roles", json={"role": "role.process.owner"})
    assert r.status_code == 201
    assert "role.process.owner" in r.json()["roles"]

    # duplicate → 409
    dup = await client.post(f"/users/{uid}/roles", json={"role": "role.process.owner"})
    assert dup.status_code == 409

    # filter by role
    by_role = await client.get("/users", params={"role": "role.process.owner"})
    assert [u["amendia_user_id"] for u in by_role.json()] == [uid]

    # revoke
    rev = await client.delete(f"/users/{uid}/roles/role.process.owner")
    assert rev.status_code == 200
    assert "role.process.owner" not in rev.json()["roles"]

    # revoke again → 404
    rev2 = await client.delete(f"/users/{uid}/roles/role.process.owner")
    assert rev2.status_code == 404


async def test_admin_disable_enable(client, resolve_service):
    resolved = await resolve_service.resolve(iss="kc", sub="u2", email="u2@x.dev")
    uid = resolved.amendia_user_id
    dis = await client.post(f"/users/{uid}/disable")
    assert dis.status_code == 200 and dis.json()["status"] == "disabled"
    # A disabled user resolves with status disabled (enforcement 403 lives in the lib).
    again = await resolve_service.resolve(iss="kc", sub="u2")
    assert again.status == "disabled"
    en = await client.post(f"/users/{uid}/enable")
    assert en.status_code == 200 and en.json()["status"] == "active"


async def test_assign_invalid_role_rejected(client, resolve_service):
    resolved = await resolve_service.resolve(iss="kc", sub="u3", email="u3@x.dev")
    r = await client.post(f"/users/{resolved.amendia_user_id}/roles", json={"role": "NOT-A-ROLE"})
    assert r.status_code == 422  # RoleId pattern rejects it


# ----------------------- pending (staged) access ---------------------------- #
async def test_pending_requires_admin(client, holder):
    holder.user = make_user(user_id="usr-m", roles=("role.payments.ops_analyst",))
    r = await client.get("/pending-role-assignments")
    assert r.status_code == 403


async def test_pending_crud(client):
    # stage (mixed-case email is normalised)
    created = await client.post(
        "/pending-role-assignments",
        json={"email": "New@X.dev", "roles": ["role.payments.ops_analyst"]},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["email"] == "new@x.dev"
    assert body["roles"] == ["role.payments.ops_analyst"]
    assert body["staged_by"] == "usr-priya"  # the default admin caller
    assert body["staged_at"]

    # list + case-insensitive substring filter
    listed = await client.get("/pending-role-assignments", params={"email": "NEW"})
    assert [p["email"] for p in listed.json()] == ["new@x.dev"]

    # replace the staged set
    replaced = await client.put(
        "/pending-role-assignments/new@x.dev", json={"roles": ["role.process.owner"]}
    )
    assert replaced.status_code == 200
    assert replaced.json()["roles"] == ["role.process.owner"]

    # delete, then delete again → 404
    d1 = await client.delete("/pending-role-assignments/new@x.dev")
    assert d1.status_code == 204
    d2 = await client.delete("/pending-role-assignments/new@x.dev")
    assert d2.status_code == 404


async def test_stage_existing_user_conflicts_with_pointer(client, resolve_service):
    resolved = await resolve_service.resolve(iss="kc", sub="ex", email="ex@x.dev", name="Ex")
    r = await client.post(
        "/pending-role-assignments",
        json={"email": "ex@x.dev", "roles": ["role.process.owner"]},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "user_exists"
    assert detail["amendia_user_id"] == resolved.amendia_user_id


async def test_stage_invalid_role_rejected(client):
    r = await client.post(
        "/pending-role-assignments", json={"email": "x@x.dev", "roles": ["NOT-A-ROLE"]}
    )
    assert r.status_code == 422


async def test_pending_attaches_on_first_login(client, resolve_service):
    await client.post(
        "/pending-role-assignments",
        json={"email": "jit@x.dev", "roles": ["role.payments.ops_analyst"]},
    )
    resolved = await resolve_service.resolve(iss="kc", sub="jit", email="jit@x.dev")
    assert "role.payments.ops_analyst" in resolved.roles


# ------------------------------ guardrails ---------------------------------- #
async def test_revoke_own_admin_blocked_self(client, resolve_service, role_repo, holder):
    resolved = await resolve_service.resolve(iss="kc", sub="alex", email="alex@x.dev")
    uid = resolved.amendia_user_id
    await role_repo.assign(uid, "role.platform.admin", "seed")
    holder.user = make_user(user_id=uid, roles=("role.platform.admin",))

    r = await client.delete(f"/users/{uid}/roles/role.platform.admin")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "self_protection"
    assert "role.platform.admin" in await role_repo.roles_for(uid)  # not removed


async def test_disable_self_blocked(client, resolve_service, holder):
    resolved = await resolve_service.resolve(iss="kc", sub="self", email="self@x.dev")
    uid = resolved.amendia_user_id
    holder.user = make_user(user_id=uid, roles=("role.platform.admin",))

    r = await client.post(f"/users/{uid}/disable")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "self_protection"


async def test_revoke_last_admin_blocked_and_restored(client, resolve_service, role_repo, holder):
    # bob is the only active admin holder; the caller (a different admin) tries to
    # strip bob's admin role — refused, and the assignment is restored.
    bob = await resolve_service.resolve(iss="kc", sub="bob", email="bob@x.dev")
    bid = bob.amendia_user_id
    await role_repo.assign(bid, "role.platform.admin", "seed")
    holder.user = make_user(user_id="usr-caller", roles=("role.platform.admin",))

    r = await client.delete(f"/users/{bid}/roles/role.platform.admin")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "last_admin"
    assert "role.platform.admin" in await role_repo.roles_for(bid)  # restored


async def test_disable_last_admin_blocked_and_rolled_back(client, resolve_service, role_repo, user_repo, holder):
    bob = await resolve_service.resolve(iss="kc", sub="bob2", email="bob2@x.dev")
    bid = bob.amendia_user_id
    await role_repo.assign(bid, "role.platform.admin", "seed")
    holder.user = make_user(user_id="usr-caller", roles=("role.platform.admin",))

    r = await client.post(f"/users/{bid}/disable")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "last_admin"
    still = await user_repo.get(bid)
    assert still.status.value == "active"  # rolled back


async def test_revoke_admin_succeeds_when_another_admin_remains(
    client, resolve_service, role_repo, holder
):
    a = await resolve_service.resolve(iss="kc", sub="adm-a", email="a@x.dev")
    b = await resolve_service.resolve(iss="kc", sub="adm-b", email="b@x.dev")
    await role_repo.assign(a.amendia_user_id, "role.platform.admin", "seed")
    await role_repo.assign(b.amendia_user_id, "role.platform.admin", "seed")
    holder.user = make_user(user_id="usr-caller", roles=("role.platform.admin",))

    r = await client.delete(f"/users/{a.amendia_user_id}/roles/role.platform.admin")
    assert r.status_code == 200
    assert "role.platform.admin" not in r.json()["roles"]


# ------------------------------ seed ---------------------------------------- #
async def test_seed_idempotent(role_repo):
    from app.seeding.seed import seed_role_assignments

    first = await seed_role_assignments(role_repo)
    assert first["added"] and not first["skipped"]
    second = await seed_role_assignments(role_repo)
    assert not second["added"] and second["skipped"]
