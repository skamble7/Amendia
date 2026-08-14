# backend/tests/smoke/hitl.py
"""Generalized HITL resolver — the ``demo_wire_repair.sh`` gate loop, made data-driven.

For an instance's open tasks: pick the persona for the task's role (spec ``hitl.roles`` → persona, else
``default_persona``), respecting **SoD** (if that persona is in the task's ``sod.excluded_users``, fall back to
another persona in the pool whose Amendia id isn't excluded), then claim (identity from the bearer, empty body)
and decide (``complete`` for a ``manual`` gate, else ``approve``). Best-effort per task — a transient 4xx is
logged and retried on the next pass, bounded by the scenario timeout."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .client import Tokens
from .config import SmokeConfig
from .scenarios import Scenario

logger = logging.getLogger("smoke.hitl")


def _decision(hitl_mode: str) -> str:
    return "complete" if hitl_mode == "manual" else "approve"


def _interpolate(value: Any, context: Dict[str, str]) -> Any:
    """Deep-fill ``{key}`` placeholders (e.g. ``{correlation}``) in a spec-provided output template."""
    if isinstance(value, str):
        try:
            return value.format(**context)
        except (KeyError, IndexError):
            return value
    if isinstance(value, dict):
        return {k: _interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, context) for v in value]
    return value


def _edits_for(sc: Scenario, element_id: str, context: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The human output for a MANUAL gate that produces an artifact — from the spec's ``hitl.outputs`` map
    (interpolated). None for approve gates / gates the spec doesn't cover."""
    tmpl = sc.hitl.outputs.get(element_id)
    return _interpolate(tmpl, context) if isinstance(tmpl, dict) else None


def pick_persona(sc: Scenario, tokens: Tokens, role: str, excluded: List[str]) -> Optional[str]:
    """The persona to act as for ``role`` — the mapped/default one, unless SoD excludes it, then the first
    pool persona whose Amendia user id isn't excluded. None when the whole pool is excluded (should not happen
    on a happy path)."""
    base = sc.hitl.roles.get(role, sc.hitl.default_persona)
    excluded_set = set(excluded or [])
    ordered = [base] + [p for p in sc.persona_pool if p != base]
    for persona in ordered:
        if tokens.user_id(persona) not in excluded_set:
            return persona
    return base if base not in [None, ""] else None


def _tasks(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario,
           instance_id: str, status: str) -> List[dict]:
    try:
        r = http.get(f"{cfg.runtime}/hitl-tasks?status={status}&process_instance_id={instance_id}",
                     headers=tokens.headers(sc.hitl.default_persona))
        return r.json() if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []


def _persona_by_user_id(sc: Scenario, tokens: Tokens, user_id: Optional[str]) -> Optional[str]:
    for persona in sc.persona_pool:
        if tokens.user_id(persona) == user_id:
            return persona
    return None


def resolve_open_for(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario,
                     instance_id: str, context: Optional[Dict[str, str]] = None) -> int:
    """One pass over ``instance_id``: claim+decide every OPEN task, and re-decide any CLAIMED task still stuck
    (e.g. a prior decide that raced) as its assignee. A manual gate that produces an artifact gets its human
    output from the spec's ``hitl.outputs`` (interpolated with ``context``). Returns the number decided."""
    ctx = context or {}
    resolved = 0
    # OPEN → claim as the SoD-correct persona, then decide.
    for task in _tasks(cfg, http, tokens, sc, instance_id, "open"):
        tid, role, mode = task.get("task_id"), task.get("role") or "", task.get("hitl_mode") or ""
        excluded = ((task.get("sod") or {}).get("excluded_users")) or []
        persona = pick_persona(sc, tokens, role, excluded)
        if not tid or not persona:
            continue
        try:
            http.post(f"{cfg.runtime}/hitl-tasks/{tid}/claim", headers=tokens.headers(persona), json={})
        except httpx.HTTPError:
            pass
        if _decide(cfg, http, tokens, sc, task, persona, ctx):
            resolved += 1
    # CLAIMED-but-undecided → decide as whoever holds it (recovers a stuck gate).
    for task in _tasks(cfg, http, tokens, sc, instance_id, "claimed"):
        persona = _persona_by_user_id(sc, tokens, task.get("assignee"))
        if persona and _decide(cfg, http, tokens, sc, task, persona, ctx):
            resolved += 1
    return resolved


def _decide(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario,
            task: dict, persona: str, ctx: Dict[str, str]) -> bool:
    tid, role, mode = task.get("task_id"), task.get("role") or "", task.get("hitl_mode") or ""
    element_id = task.get("element_id") or ""
    body: Dict[str, Any] = {"decision": _decision(mode)}
    edits = _edits_for(sc, element_id, ctx)
    if edits is not None:
        body["edits"] = edits
    try:
        r = http.post(f"{cfg.runtime}/hitl-tasks/{tid}/decide", headers=tokens.headers(persona), json=body)
    except httpx.HTTPError as exc:
        logger.info("[%s] gate %s decide error (will retry): %s", sc.domain, tid, exc)
        return False
    if r.status_code < 300:
        logger.info("[%s] resolved gate %s (mode=%s role=%s) as %s", sc.domain, element_id, mode, role, persona)
        return True
    logger.info("[%s] gate %s (%s) decide → %s: %s", sc.domain, element_id, mode, r.status_code, r.text[:160])
    return False
