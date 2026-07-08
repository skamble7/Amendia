# app/services/resolver.py
"""Triage resolution over active packs, with a small TTL cache.

v1 evaluates rules directly against active packs from Mongo. The cache is the seam
where a compiled/materialized triage index would later slot in.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from app.dal.pack_repo import ProcessPackRepository
from app.models.registry import ResolveResponse
from app.validation.predicates import evaluate
from app.validation.semver_key import version_desc_key


def _scope_covers(tenant_scope: Any, tenant: str) -> bool:
    if tenant_scope is None or tenant_scope == "global":
        return True
    return isinstance(tenant_scope, list) and tenant in tenant_scope


class ResolveService:
    def __init__(self, pack_repo: ProcessPackRepository, ttl_seconds: float = 30.0) -> None:
        self._repo = pack_repo
        self._ttl = ttl_seconds
        self._cache: Optional[List[dict]] = None
        self._cached_at: float = -1e9

    async def _active_packs(self) -> List[dict]:
        now = time.monotonic()
        if self._cache is None or (now - self._cached_at) > self._ttl:
            self._cache = await self._repo.list_active_raw()
            self._cached_at = now
        return self._cache

    def invalidate(self) -> None:
        self._cache = None

    async def resolve(self, tenant: str, envelope: Dict[str, Any]) -> Tuple[Optional[ResolveResponse], int]:
        packs = await self._active_packs()
        in_scope = [p for p in packs if _scope_covers(p.get("tenant_scope"), tenant)]

        # (priority, pack_key, version, rule_id) for every matching rule.
        candidates: List[Tuple[int, str, str, str]] = []
        for p in in_scope:
            for rule in p.get("triage_rules", []):
                if evaluate(rule["when"], envelope):
                    candidates.append((rule.get("priority", 0), p["pack_key"], p["version"], rule["rule_id"]))

        if not candidates:
            return None, len(in_scope)

        # priority asc, pack_key asc, version desc, rule_id asc (fully deterministic).
        candidates.sort(key=lambda c: (c[0], c[1], version_desc_key(c[2]), c[3]))
        priority, pack_key, version, rule_id = candidates[0]
        return ResolveResponse(pack_key=pack_key, pack_version=version, rule_id=rule_id), len(in_scope)
