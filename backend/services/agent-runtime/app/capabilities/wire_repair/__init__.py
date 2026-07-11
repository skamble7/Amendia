# app/capabilities/wire_repair/__init__.py
"""Simulated wire-repair capabilities + the capability_id → callable registry.

Skill-kind capabilities are resolved by the descriptor's ``runtime.entrypoint``
(``app.capabilities.wire_repair.<mod>:run``). llm/mcp-kind capabilities have no
real backend in this slice; the executor routes them to the SAME functions in
simulation mode via ``SIM_CAPABILITIES`` keyed by capability_id.
"""
from __future__ import annotations

from app.capabilities.wire_repair import (
    apply_repair,
    assess,
    assess_agentic,
    draft_repair,
    draft_return,
    draft_rfi,
    enrich,
    execute_return,
    notify,
    record_resolution,
    sanctions,
)

# capability_id -> run(**kwargs) callable
SIM_CAPABILITIES = {
    "cap.payment.enrich_investigation": enrich.run,
    "cap.payment.assess_beneficiary": assess.run,
    # ADR-021 pilot deep_agent — deterministic stand-in for the FakeDeepAgentRunner.
    "cap.payment.assess_beneficiary_agentic": assess_agentic.run,
    "cap.payment.draft_rfi": draft_rfi.run,
    "cap.payment.draft_repair": draft_repair.run,
    "cap.payment.sanctions_screen": sanctions.run,
    "cap.payment.apply_repair": apply_repair.run,
    "cap.payment.notify_parties": notify.run,
    "cap.payment.record_resolution": record_resolution.run,
    "cap.payment.draft_return": draft_return.run,
    "cap.payment.execute_return": execute_return.run,
}

__all__ = ["SIM_CAPABILITIES"]
