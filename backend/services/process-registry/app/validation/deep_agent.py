# app/validation/deep_agent.py
"""Registry validation rules for the ``deep_agent`` capability kind (ADR-021).

A `deep_agent` runs a bounded agent loop inside one node — powerful, so onboarding gates it
with four deterministic checks (design §9.4). All additive: packs with no deep_agent binding
are untouched.
"""
from __future__ import annotations

from typing import Dict

from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.common import HitlMode
from amendia_contracts.process_pack import ProcessPackManifest
from app.validation.report import ValidationReport

# Named worker functions a deep_agent may call (read-only investigation helpers). The actual
# implementations live in the agent-runtime worker; the registry only checks the id resolves.
KNOWN_WORKER_TOOLS = {
    "fetch_attachment",
    "search_payment_history",
    "name_match",
    "screen_party",
}


def _kind(desc: CapabilityDescriptor) -> str:
    return desc.kind.value if hasattr(desc.kind, "value") else str(desc.kind)


def validate_deep_agent_bindings(
    manifest: ProcessPackManifest,
    resolved: Dict[str, CapabilityDescriptor],
    report: ValidationReport,
) -> None:
    """Stage-4 addendum: enforce the deep_agent rules for every binding that resolves to a
    deep_agent capability."""
    # Tool universe: known worker functions + every tool declared by an mcp capability in
    # this pack (that's what "resolves to a registered MCP tool" means here).
    mcp_tools: set = set()
    for desc in resolved.values():
        if _kind(desc) == "mcp":
            mcp_tools.update(getattr(desc.runtime, "tools", []) or [])
    resolvable = KNOWN_WORKER_TOOLS | mcp_tools

    pack_has_deep_agent = False
    for b in manifest.bindings:
        ex = b.executor
        if ex.type != "capability":
            continue
        desc = resolved.get(ex.capability.ref_id)
        if desc is None or _kind(desc) != "deep_agent":
            continue
        pack_has_deep_agent = True
        el = b.element_id

        # Rule 3 — must be behind a HITL gate (never `none`).
        if b.hitl.mode is HitlMode.NONE:
            report.error("deep_agent_requires_hitl", stage=4, element_id=el,
                         message=f"deep_agent capability '{desc.capability_id}' must be bound behind a "
                                 f"HITL gate (review_after / approve_result / manual), not 'none'")

        # Rule 2 — read_only unless the pack carries an explicit justification.
        if desc.side_effect.value == "side_effectful":
            if not manifest.deep_agent_justifications.get(desc.capability_id):
                report.error("deep_agent_side_effect_not_justified", stage=4, element_id=el,
                             message=f"side-effectful deep_agent '{desc.capability_id}' is refused unless "
                                     f"deep_agent_justifications['{desc.capability_id}'] is provided")

        # Rule 1 — every whitelisted tool resolves.
        for tool in getattr(desc.runtime, "tools", []) or []:
            if tool not in resolvable:
                report.error("deep_agent_tool_unresolved", stage=4, element_id=el,
                             message=f"deep_agent '{desc.capability_id}' tool '{tool}' does not resolve to a "
                                     f"known worker function or a registered MCP tool in this pack")

    # Rule 4 — mode-required: a pack with a deep_agent binding may only run where nemoclaw
    # mode is available (ADR-017 §4.3). The registry can't see runtime mode, so it surfaces a
    # clear, deterministic marker; the agent-runtime fail-closes at execution (ADR-021 Part D).
    if pack_has_deep_agent:
        report.warning("deep_agent_pack_requires_nemoclaw_mode", stage=4,
                       message="this pack binds a deep_agent capability and may only activate/run where "
                               "AGENTRT_EXECUTION_MODE=nemoclaw is available")
