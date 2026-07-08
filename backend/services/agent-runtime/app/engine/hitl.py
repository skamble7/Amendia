# app/engine/hitl.py
"""Pure HITL helpers: the allowed-decisions table and SoD exclusion computation.

These are framework-free so the task runner (in-graph) and the engine
(materializing the HitlTask doc) share one source of truth. Reference:
amendia_contracts_reference.md §7.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from amendia_contracts.hitl_task import Decision

# hitl_mode → allowed decisions (§7 table)
ALLOWED_DECISIONS: Dict[str, List[Decision]] = {
    "review_after": [Decision.APPROVE, Decision.EDIT_AND_APPROVE, Decision.REJECT],
    "approve_result": [Decision.APPROVE, Decision.REJECT],
    "approve_actions": [Decision.APPROVE, Decision.REJECT],
    "manual": [Decision.COMPLETE, Decision.ESCALATE],
}


def allowed_decisions_for(mode: str) -> List[Decision]:
    if mode not in ALLOWED_DECISIONS:
        raise ValueError(f"no allowed_decisions for hitl mode {mode!r}")
    return list(ALLOWED_DECISIONS[mode])


def compute_sod_excluded(
    sod_policies: List[Any], actor_log: List[Dict[str, Any]], element_id: str
) -> Tuple[List[str], List[str]]:
    """Users excluded from acting on ``element_id`` by ``distinct_actor`` policies.

    A user is excluded if they already acted (as a human) on another element that
    shares a ``distinct_actor`` constraint with this one. Returns
    ``(excluded_users, derived_from)``.
    """
    excluded: set[str] = set()
    derived: List[str] = []
    for pol in sod_policies or []:
        constraint = getattr(pol, "constraint", None) or (pol.get("constraint") if isinstance(pol, dict) else None)
        elements = getattr(pol, "elements", None) or (pol.get("elements") if isinstance(pol, dict) else [])
        if constraint != "distinct_actor" or element_id not in elements:
            continue
        others = [e for e in elements if e != element_id]
        for entry in actor_log or []:
            if entry.get("kind") == "human" and entry.get("element_id") in others:
                user = entry.get("actor")
                if user:
                    excluded.add(user)
                    derived.append(
                        f"distinct_actor[{'|'.join(elements)}]: {user} already acted on {entry.get('element_id')}"
                    )
    return sorted(excluded), derived
