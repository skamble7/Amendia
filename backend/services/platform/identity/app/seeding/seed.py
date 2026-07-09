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


async def seed_role_assignments(role_repo: RoleRepository) -> dict:
    added, skipped = [], []
    for email, roles in SEED_ROLES.items():
        for role in roles:
            if await role_repo.add_pending(email, role, "seed"):
                added.append(f"{email}:{role}")
            else:
                skipped.append(f"{email}:{role}")
    report = {"added": added, "skipped": skipped}
    logger.info("identity seed (pending role assignments): %s", report)
    return report
