# app/seeding/seed.py
"""Idempotent role-assignment seed for the three dev personas.

Strategy (chosen from the two the task allows): seed role assignments **keyed by
email**, not by a hardcoded Keycloak ``sub``. JIT provisioning materialises them
onto the user on first login (``ResolveService._materialise_pending_roles``). This
survives realm re-imports (no brittle UUIDs) and needs no Keycloak admin call at
seed time. The emails here MUST match the realm export users' emails.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository

logger = logging.getLogger(__name__)

# email → seeded roles. Keep in lockstep with backend/deploy/keycloak/amendia-dev-realm.json.
# alex is platform-admin-only (proves the admin-only nav composition); sam is
# deliberately absent here so his first login lands in the roleless state.
SEED_ROLES: Dict[str, List[str]] = {
    "riya@amendia.dev": ["role.payments.ops_analyst"],
    "marcus@amendia.dev": ["role.payments.ops_approver"],
    "priya@amendia.dev": ["role.process.owner", "role.platform.admin"],
    "alex@amendia.dev": ["role.platform.admin"],
}


async def seed_role_assignments(role_repo: RoleRepository, user_repo: UserRepository) -> dict:
    """Stage the dev-persona roles by email. Skips any email that already belongs to a
    provisioned user — its roles are already live on the user, and re-staging would
    resurrect a row in the Pending tab for someone who has clearly signed in."""
    added, skipped = [], []
    for email, roles in SEED_ROLES.items():
        if await user_repo.get_by_email(email) is not None:
            skipped.append(f"{email}:already-provisioned")
            continue
        for role in roles:
            if await role_repo.add_pending(email, role, "seed"):
                added.append(f"{email}:{role}")
            else:
                skipped.append(f"{email}:{role}")
    report = {"added": added, "skipped": skipped}
    logger.info("identity seed (pending role assignments): %s", report)
    return report


async def reconcile_pending(role_repo: RoleRepository, user_repo: UserRepository) -> List[str]:
    """Self-heal stale staged access: delete any pending rows whose email already
    belongs to a provisioned user. Runs at every startup, so a deployment that predates
    the delete-on-materialise fix converges to the invariant (pending ⇔ not-yet-signed-in)
    without a manual migration. Returns the emails purged."""
    emails = await role_repo.pending_emails()
    in_use = await user_repo.emails_in_use(emails)
    purged: List[str] = []
    for email in sorted(in_use):
        if await role_repo.delete_pending(email):
            purged.append(email)
    if purged:
        logger.info("pending reconcile purged staged access for provisioned users: %s", purged)
    return purged
