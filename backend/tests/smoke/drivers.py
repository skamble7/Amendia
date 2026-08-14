# backend/tests/smoke/drivers.py
"""Trigger drivers — one per ``trigger.kind`` in a scenario spec. Each fires the domain's REAL trigger against
the running stack and returns a ``Handle`` (the correlation value + an optional single trigger id to follow
through the ingestor). Adding a domain reuses a driver via its spec; a genuinely new mechanism is a new entry
in ``DRIVERS`` — never a change to the test body."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx

from .client import Tokens
from .config import SmokeConfig
from .scenarios import Scenario


@dataclass(frozen=True)
class Handle:
    correlation: str                 # the value that resolves the case (case_id / trigger_id)
    trigger_id: Optional[str] = None  # a single trigger to follow via the ingestor (None for cohort/multi)


class DriverError(RuntimeError):
    """The trigger could not be fired (service down / bad request) — the caller skips or fails clearly."""


def _pega_stub(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario) -> Handle:
    """ACH: POST a case to the mock Pega orchestrator; it fires Segment A and the MCP handbacks drive B→C→close.
    The cohort is followed by ``case_id`` (the spec's ``correlation``)."""
    req = sc.trigger.get("request") or {}
    try:
        r = http.post(f"{cfg.pega_stub}/cases", json=req, timeout=15)
    except httpx.HTTPError as exc:
        raise DriverError(f"pega_stub unreachable at {cfg.pega_stub} ({exc})")
    if r.status_code >= 300:
        raise DriverError(f"pega_stub POST /cases → {r.status_code}: {r.text[:200]}")
    case = r.json()
    corr = case.get(sc.correlation) or case.get("case_id")
    if not corr:
        raise DriverError(f"pega_stub case has no '{sc.correlation}': {case}")
    return Handle(correlation=str(corr), trigger_id=case.get("triggers", {}).get("A"))


def _stub_generator(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario) -> Handle:
    """wire / restaurant: POST to the neutral generator (``/generators/{id}/generate``), which persists a
    StoredTrigger and publishes a TriggerRaised. Followed by the returned ``trigger_id``."""
    req = sc.trigger.get("request") or {}
    generator = req.get("generator")
    body = req.get("body") or {}
    if not generator:
        raise DriverError("stub_generator scenario needs trigger.request.generator")
    r = http.post(f"{cfg.stub}/generators/{generator}/generate", json=body,
                  headers=tokens.headers(sc.hitl.default_persona), timeout=15)
    if r.status_code >= 300:
        raise DriverError(f"stub /generators/{generator}/generate → {r.status_code}: {r.text[:200]}")
    created = (r.json().get("created") or [])
    if not created:
        raise DriverError(f"stub generator '{generator}' created nothing: {r.text[:200]}")
    tid = created[0]["trigger"]["trigger_id"]
    return Handle(correlation=str(tid), trigger_id=str(tid))


def _direct_trigger(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario) -> Handle:
    """Fallback: POST a sample trigger straight to the stub's neutral ``/triggers`` ingress (for a domain
    with no dedicated generator). ``request`` carries the StoredTrigger fields (trigger_type, payload)."""
    req = sc.trigger.get("request") or {}
    r = http.post(f"{cfg.stub}/triggers", json=req,
                  headers=tokens.headers(sc.hitl.default_persona), timeout=15)
    if r.status_code >= 300:
        raise DriverError(f"stub POST /triggers → {r.status_code}: {r.text[:200]}")
    tid = r.json().get("trigger_id") or (req.get("payload") or {}).get(sc.correlation)
    if not tid:
        raise DriverError(f"direct_trigger got no trigger id back: {r.text[:200]}")
    return Handle(correlation=str(tid), trigger_id=str(tid))


DRIVERS: Dict[str, Callable[[SmokeConfig, httpx.Client, Tokens, Scenario], Handle]] = {
    "pega_stub": _pega_stub,
    "stub_generator": _stub_generator,
    "direct_trigger": _direct_trigger,
}


def fire(cfg: SmokeConfig, http: httpx.Client, tokens: Tokens, sc: Scenario) -> Handle:
    kind = sc.trigger.get("kind")
    driver = DRIVERS.get(kind)
    if driver is None:
        raise DriverError(f"unknown trigger.kind '{kind}' (known: {sorted(DRIVERS)})")
    return driver(cfg, http, tokens, sc)
