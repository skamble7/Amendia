# app/services/roles.py
"""Roles in use across active packs.

Role **ids** are always *derived* from active packs' bindings (`hitl.role` +
`executor.role` for human executors) — this is universal and works for seed/API-onboarded
packs that carry no authored metadata. The per-pack ``pack_roles`` sidecar (authored during
onboarding) only *enriches* those ids with a label/description. The two code-fixed platform
roles (``role.process.owner`` / ``role.platform.admin``) are NOT surfaced here — they are a
curated frontend constant merged in at the UI layer.
"""
from __future__ import annotations

from typing import Dict, List

from app.dal.pack_repo import ProcessPackRepository
from app.models.registry import RoleInUse


def _roles_from_bindings(pack: dict) -> List[str]:
    roles: List[str] = []
    for b in pack.get("bindings", []) or []:
        hitl = b.get("hitl") or {}
        if hitl.get("role"):
            roles.append(hitl["role"])
        executor = b.get("executor") or {}
        if executor.get("type") == "human" and executor.get("role"):
            roles.append(executor["role"])
    return roles


async def list_roles_in_use(pack_repo: ProcessPackRepository) -> List[RoleInUse]:
    """Union of role ids referenced by active packs, enriched with sidecar metadata.

    Deduped by role_id; ``sources`` lists the ``pack_key@version`` packs that reference it.
    Metadata (label/description) comes from the first pack whose sidecar carries it."""
    by_id: Dict[str, RoleInUse] = {}

    for pack in await pack_repo.list_active_raw():
        pk, ver = pack.get("pack_key", ""), pack.get("version", "")
        source = f"{pk}@{ver}"
        role_ids = set(_roles_from_bindings(pack))
        if not role_ids:
            continue
        meta = {r.get("role_id"): r for r in await pack_repo.get_pack_roles(pk, ver)}
        for rid in role_ids:
            entry = by_id.get(rid)
            if entry is None:
                entry = RoleInUse(role_id=rid)
                by_id[rid] = entry
            if source not in entry.sources:
                entry.sources.append(source)
            m = meta.get(rid)
            if m and entry.label is None and m.get("label"):
                entry.label = m["label"]
                entry.description = m.get("description") or None

    for entry in by_id.values():
        entry.sources.sort()
    return sorted(by_id.values(), key=lambda r: r.role_id)
