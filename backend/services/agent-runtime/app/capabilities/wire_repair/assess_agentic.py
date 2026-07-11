# app/capabilities/wire_repair/assess_agentic.py
"""cap.payment.assess_beneficiary_agentic — the deterministic stand-in for the pilot
`deep_agent` capability (ADR-021).

The real capability runs a bounded Deep Agents loop (name-match, history search, attachment
read) to produce a `repair_verdict` **with evidence[]**. This simulation reuses the existing
`assess_beneficiary` logic (which already emits a schema-valid verdict with evidence) so the
`FakeDeepAgentRunner` and the fake OpenShell client can exercise the deep_agent node in CI/dev
with no model or agent loop. Read-only.
"""
from __future__ import annotations

from typing import Any, Dict

from app.capabilities.wire_repair import assess

ARTIFACT_KEY = assess.ARTIFACT_KEY


def run(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
        approved_action_ids=None) -> Dict[str, Any]:
    result = assess.run(inputs=inputs, envelope=envelope, mode=mode, approved_action_ids=approved_action_ids)
    # Mark provenance as an (investigative) agentic assessment; the artifact shape is identical
    # to the deterministic assess verdict (a schema-valid repair_verdict with evidence[]).
    verdict = result["outputs"][ARTIFACT_KEY]
    ev = list(verdict.get("evidence") or [])
    ev.append({"kind": "history", "detail": "agentic investigation (simulated): tools name_match + history"})
    verdict["evidence"] = ev
    return {"outputs": {ARTIFACT_KEY: verdict}, "log": "assessed repairability (agentic, simulated)"}
