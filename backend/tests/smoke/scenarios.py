# backend/tests/smoke/scenarios.py
"""Load every ``scenarios/*.yaml`` into a typed ``Scenario`` so the corpus drives the tests. Adding a new
worked-example is a new YAML file here — no Python change. The schema is intentionally small; unknown keys
are ignored so specs can carry documentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SCENARIO_DIR = Path(__file__).parent / "scenarios"


@dataclass(frozen=True)
class Hitl:
    default_persona: str = "riya"
    roles: Dict[str, str] = field(default_factory=dict)     # role id -> persona
    personas: List[str] = field(default_factory=list)       # pool for SoD fallback (defaults to the values above)
    # Optional per-gate human output for a MANUAL task that produces an artifact — element_id -> edits object.
    # String values interpolate ``{correlation}`` (the case handle) at runtime. Approve gates need none.
    outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Expect:
    instance_status: str = "completed"
    cohort: Optional[Dict[str, Any]] = None                 # {state, outcome} — present ⇒ a cohort domain


@dataclass(frozen=True)
class Scenario:
    domain: str
    pack_keys: List[str]
    trigger: Dict[str, Any]                                 # {kind, request}
    correlation: str
    hitl: Hitl
    expect: Expect
    timeout_s: float = 150.0
    skip: bool = False
    skip_reason: str = ""

    @property
    def persona_pool(self) -> List[str]:
        pool = list(dict.fromkeys([self.hitl.default_persona, *self.hitl.roles.values(), *self.hitl.personas]))
        return [p for p in pool if p]


def _scenario_from(doc: Dict[str, Any]) -> Scenario:
    hitl = doc.get("hitl") or {}
    expect = doc.get("expect") or {}
    return Scenario(
        domain=doc["domain"],
        pack_keys=list(doc.get("pack_keys") or []),
        trigger=doc.get("trigger") or {},
        correlation=doc.get("correlation") or "trigger_id",
        hitl=Hitl(default_persona=hitl.get("default_persona", "riya"),
                  roles=dict(hitl.get("roles") or {}), personas=list(hitl.get("personas") or []),
                  outputs=dict(hitl.get("outputs") or {})),
        expect=Expect(instance_status=expect.get("instance_status", "completed"),
                      cohort=expect.get("cohort")),
        timeout_s=float(doc.get("timeout_s", 150)),
        skip=bool(doc.get("skip", False)),
        skip_reason=str(doc.get("skip_reason", "")),
    )


def load_scenarios() -> List[Scenario]:
    out = [_scenario_from(yaml.safe_load(p.read_text())) for p in sorted(SCENARIO_DIR.glob("*.yaml"))]
    return sorted(out, key=lambda s: s.domain)
