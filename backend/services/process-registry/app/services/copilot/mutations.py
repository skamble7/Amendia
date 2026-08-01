# app/services/copilot/mutations.py
"""ADR-052 Phase 2b — the constrained, typed mutation vocabulary + the session⇄proposal bridge.

The chat LLM never writes session state. It emits a `CopilotEdit` = a plain-language reply + a closed set of
typed `Mutation`s (or a clarifying question and NO mutations). We reconstruct a `CopilotProposal` from the CURRENT
draft, apply the mutations to that proposal (a thin editing layer), and hand it back to `reconcile.py` — so every
edit flows through the SAME deterministic disposer (bijection, side-effect/HITL floors, ADR-051 alignment,
ADR-050 human-authored derivation). No second enforcement path; floors are clamped there, not here.

Domain-neutral: only generic element/tool/field/artifact names.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.models.onboarding import (
    CopilotMcpConfig,
    CopilotReport,
    IntrospectedTool,
    IntrospectMcpResponse,
    OnboardingSession,
    ToolCompliance,
)
from app.services.copilot.proposal import (
    CopilotProposal,
    ElementProposal,
    ExecutorProposal,
    HitlProposal,
    InputMapProposal,
    OutputFieldProposal,
    OutputProposal,
    ReadOnlyInputProposal,
    TriageRuleProposal,
)
from app.services.mcp_introspect import sanitize_name

# The closed mutation vocabulary (the LLM may only emit these ``kind`` values).
MUTATION_KINDS = {
    "set_hitl", "set_executor", "set_input_map_field", "remove_input_map_field", "set_input_optional",
    "set_output_name", "add_read_only_input", "remove_read_only_input", "set_side_effect",
    "edit_trigger", "add_triage_rule", "edit_triage_rule", "remove_triage_rule", "resolve_open_question",
}


class Mutation(BaseModel):
    """One typed edit. Permissive (extra ignored) — the applier reads only the fields its ``kind`` uses."""
    model_config = ConfigDict(extra="ignore")
    kind: str
    element_id: Optional[str] = None
    rationale: Optional[str] = None
    # set_hitl / set_executor
    mode: Optional[str] = None
    role: Optional[str] = None
    capability_tool: Optional[str] = None
    message_name: Optional[str] = None
    call: Optional[str] = None
    # input_map
    field: Optional[str] = None
    source: Optional[Dict[str, Any]] = None          # {from, name?, path?, optional?}
    input: Optional[str] = None                       # composite input name (advisory; matched by field)
    optional: Optional[bool] = None                   # set_input_optional target
    # output naming
    output: Optional[str] = None                      # which output to rename (human); omit for capability
    new_name: Optional[str] = None
    # read-only context
    name: Optional[str] = None
    source_output: Optional[str] = None
    # side effect
    tool: Optional[str] = None
    side_effect: Optional[str] = None
    # trigger
    trigger_field: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_remove: Optional[bool] = None
    # triage
    rule_id: Optional[str] = None
    when: Optional[Dict[str, Any]] = None
    priority: Optional[int] = None
    # open questions
    question_id: Optional[str] = None
    resolution: Optional[str] = None


class CopilotEdit(BaseModel):
    """The chat LLM's structured output: a reply + either typed mutations OR a clarifying question."""
    model_config = ConfigDict(extra="ignore")
    reply: str = ""
    needs_clarification: bool = False
    mutations: List[Mutation] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Reconstruct the copilot's inputs from the current draft session
# --------------------------------------------------------------------------- #
def _tool_of(capability_ref: Optional[str]) -> Optional[str]:
    if not capability_ref:
        return None
    core = capability_ref.split("@", 1)[0]        # cap.<domain>.<tool>
    parts = core.split(".", 2)
    return parts[2] if len(parts) == 3 else None


def open_question_id(q) -> str:
    """A stable id for an open question (topic[:element_id]) so a mutation can resolve it by reference."""
    return f"{q.topic}:{q.element_id}" if q.element_id else q.topic


def _fields_from_schema(schema: Any) -> Optional[List[OutputFieldProposal]]:
    """Reverse a human artifact's JSON schema back into baseline OutputFieldProposals, so a chat turn's re-derivation
    preserves the copilot baseline AND any operator refinement instead of clobbering it to an empty form."""
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out: List[OutputFieldProposal] = []
    for fname, s in props.items():
        of = OutputFieldProposal(name=fname, required=fname in required)
        if isinstance(s, dict):
            if s.get("enum"):
                of.type, of.enum = "string", list(s["enum"])
            elif s.get("type") == "array":
                items = s.get("items")
                of.type, of.items = "array", (items.get("type") if isinstance(items, dict) else "string")
            elif s.get("type") == "object":
                of.type, of.properties = "object", _fields_from_schema(s)
            else:
                of.type = s.get("type") or "string"
            if s.get("title"):
                of.title = s["title"]
            if s.get("description"):
                of.description = s["description"]
        out.append(of)
    return out or None


def proposal_from_session(session: OnboardingSession) -> CopilotProposal:
    """Reverse the composed draft back into a CopilotProposal — the editable surface the mutations act on."""
    authored_schema = {a.artifact_key: a.json_schema for a in (getattr(session, "authored_artifacts", None) or [])}
    basics = getattr(session, "basics", None)
    domain = basics.default_domain if basics else ""
    elements: List[ElementProposal] = []
    for b in session.bindings:
        ep = ElementProposal(element_id=b.element_id, executor=ExecutorProposal(type=b.executor_type),
                             hitl=HitlProposal(mode=b.hitl_mode or "none", role=b.hitl_role))
        if b.executor_type == "capability":
            tool = _tool_of(b.capability_ref)
            ep.executor.capability_tool = tool
            if b.outputs:
                ep.output_name = b.outputs[0].name
            fields = (b.input_sources or {}).get(f"{sanitize_name(tool)}_input", {}).get("fields", {}) if tool else {}
            ep.input_map = [InputMapProposal(field=f, **{"from": s.get("from", "trigger")},
                                             name=s.get("name"), path=s.get("path"), optional=s.get("optional"))
                            for f, s in fields.items() if isinstance(s, dict)]
        elif b.executor_type == "human":
            ep.executor.role = b.role
            ep.outputs = [OutputProposal(name=o.name, human_authored=True,
                                         fields=_fields_from_schema(authored_schema.get(f"art.{domain}.{o.name}")))
                          for o in b.outputs]
            for io in b.inputs:
                src = (b.input_sources or {}).get(io.name, {})
                if isinstance(src, dict) and src.get("name"):
                    ep.read_only_inputs.append(ReadOnlyInputProposal(
                        name=io.name, source_output=src["name"], optional=src.get("optional")))
        elif b.executor_type == "message":
            ep.executor.message_name = b.message_name
        elif b.executor_type == "call":
            ep.executor.call = b.call_pack
        elements.append(ep)

    triage = [TriageRuleProposal(rule_id=r.rule_id, priority=r.priority, description=r.description, when=r.when)
              for r in session.triage_rules]
    trigger_schema = session.trigger_artifact.json_schema if session.trigger_artifact else None
    return CopilotProposal(summary=(session.copilot_report.summary if session.copilot_report else ""),
                           elements=elements, trigger_schema=copy.deepcopy(trigger_schema), triage_rules=triage)


def tools_from_session(session: OnboardingSession) -> IntrospectMcpResponse:
    """Rebuild the tool catalog from the staged capabilities + their staged I/O artifact schemas — so a chat turn
    re-runs reconcile WITHOUT re-introspecting the MCP server."""
    schema_by_key = {a.artifact_key: a.json_schema for a in session.staged_artifacts}
    tools: List[IntrospectedTool] = []
    endpoint = ""
    for sc in session.staged_capabilities:
        if sc.kind != "mcp" or not sc.tool:
            continue
        endpoint = endpoint or (sc.endpoint or "")
        tools.append(IntrospectedTool(
            name=sc.tool, description=sc.description,
            input_schema=schema_by_key.get(sc.input_artifact_key),
            output_schema=schema_by_key.get(sc.output_artifact_key),
            compliance=ToolCompliance(compliant=True),
            suggested_input_artifact_key=sc.input_artifact_key,
            suggested_output_artifact_key=sc.output_artifact_key,
            suggested_capability_id=sc.capability_id, suggested_side_effect=sc.side_effect))
    return IntrospectMcpResponse(endpoint=endpoint, transport="streamable_http", tools=tools)


def mcp_from_session(session: OnboardingSession) -> CopilotMcpConfig:
    for sc in session.staged_capabilities:
        if sc.kind == "mcp" and sc.endpoint:
            return CopilotMcpConfig(endpoint=sc.endpoint, transport=sc.transport, headers=dict(sc.headers or {}))
    return CopilotMcpConfig(endpoint="")


def trigger_name_from_session(session: OnboardingSession) -> str:
    if session.trigger_artifact:
        parts = session.trigger_artifact.artifact_key.split(".", 2)
        if len(parts) == 3:
            return parts[2]
    return "trigger"


# --------------------------------------------------------------------------- #
# Apply the typed mutations to the reconstructed proposal (+ tools for side-effect)
# --------------------------------------------------------------------------- #
def apply_mutations(proposal: CopilotProposal, tools: IntrospectMcpResponse,
                    report: Optional[CopilotReport], mutations: List[Mutation]) -> List[str]:
    """Mutate the proposal (and the tool catalog for ``set_side_effect``) in place. Returns human-readable
    summaries of what was applied (for the conversation log + provenance). Unknown/empty mutations are skipped."""
    by_el = proposal.by_element()
    tool_by_name = {t.name: t for t in tools.tools}
    applied: List[str] = []

    def el(mid: Optional[str]) -> Optional[ElementProposal]:
        return by_el.get(mid) if mid else None

    for m in mutations:
        if m.kind not in MUTATION_KINDS:
            continue
        note = m.rationale or ""
        if m.kind == "set_hitl" and el(m.element_id):
            e = el(m.element_id)
            if m.mode is not None:
                e.hitl.mode = m.mode
            if m.role is not None:
                e.hitl.role = m.role
            applied.append(f"{m.element_id}: HITL → mode={m.mode or e.hitl.mode}, role={m.role or e.hitl.role}. {note}")
        elif m.kind == "set_executor" and el(m.element_id):
            e = el(m.element_id)
            if m.capability_tool:
                e.executor.type = "capability"
                e.executor.capability_tool = m.capability_tool
            elif m.role:
                e.executor.type = "human"
                e.executor.role = m.role
            elif m.message_name:
                e.executor.type = "message"
                e.executor.message_name = m.message_name
            elif m.call:
                e.executor.type = "call"
                e.executor.call = m.call
            applied.append(f"{m.element_id}: executor → {e.executor.type}. {note}")
        elif m.kind == "set_input_map_field" and el(m.element_id) and m.field:
            e = el(m.element_id)
            src = m.source or {}
            e.input_map = [im for im in e.input_map if im.field != m.field]
            e.input_map.append(InputMapProposal(field=m.field, **{"from": src.get("from", "trigger")},
                                                name=src.get("name"), path=src.get("path"),
                                                optional=src.get("optional")))
            applied.append(f"{m.element_id}: input '{m.field}' ← {src}. {note}")
        elif m.kind == "set_input_optional" and el(m.element_id) and m.field:
            # ADR-048/052: toggle absent-tolerance for a loop-back / not-guaranteed input. reconcile is
            # authoritative on the generate path (flow graph); this is the conversational override on the
            # chat path, where the flag round-trips through the reconstructed proposal source.
            e = el(m.element_id)
            opt = True if m.optional is None else bool(m.optional)
            for im in e.input_map:
                if im.field == m.field:
                    im.optional = opt
            applied.append(f"{m.element_id}: input '{m.field}' optional → {opt}. {note}")
        elif m.kind == "remove_input_map_field" and el(m.element_id) and m.field:
            e = el(m.element_id)
            e.input_map = [im for im in e.input_map if im.field != m.field]
            applied.append(f"{m.element_id}: removed input mapping '{m.field}'. {note}")
        elif m.kind == "set_output_name" and el(m.element_id) and m.new_name:
            e = el(m.element_id)
            if e.executor.type == "capability":
                e.output_name = m.new_name
            else:
                for o in e.outputs:
                    if not m.output or o.name == m.output:
                        o.name = m.new_name
            applied.append(f"{m.element_id}: output name → '{m.new_name}'. {note}")
        elif m.kind == "add_read_only_input" and el(m.element_id) and m.name and m.source_output:
            e = el(m.element_id)
            e.read_only_inputs = [r for r in e.read_only_inputs if r.name != m.name]
            e.read_only_inputs.append(ReadOnlyInputProposal(name=m.name, source_output=m.source_output))
            applied.append(f"{m.element_id}: reads '{m.name}' ← {m.source_output} (read-only). {note}")
        elif m.kind == "remove_read_only_input" and el(m.element_id) and m.name:
            e = el(m.element_id)
            e.read_only_inputs = [r for r in e.read_only_inputs if r.name != m.name]
            applied.append(f"{m.element_id}: removed read-only input '{m.name}'. {note}")
        elif m.kind == "set_side_effect" and m.tool in tool_by_name and m.side_effect:
            tool_by_name[m.tool].suggested_side_effect = m.side_effect
            applied.append(f"tool '{m.tool}': side_effect → {m.side_effect} (re-triggers the HITL floor). {note}")
        elif m.kind == "edit_trigger" and m.trigger_field:
            schema = proposal.trigger_schema or {"type": "object", "properties": {}}
            props = schema.setdefault("properties", {})
            if m.trigger_remove:
                props.pop(m.trigger_field, None)
            else:
                props[m.trigger_field] = {"type": m.trigger_type or "string"}
            proposal.trigger_schema = schema
            applied.append(f"trigger: {'removed' if m.trigger_remove else 'set'} field '{m.trigger_field}'. {note}")
        elif m.kind == "add_triage_rule" and m.rule_id and m.when:
            proposal.triage_rules = [r for r in proposal.triage_rules if r.rule_id != m.rule_id]
            proposal.triage_rules.append(TriageRuleProposal(rule_id=m.rule_id, priority=m.priority or 100, when=m.when))
            applied.append(f"triage: added rule '{m.rule_id}'. {note}")
        elif m.kind == "edit_triage_rule" and m.rule_id:
            for r in proposal.triage_rules:
                if r.rule_id == m.rule_id:
                    if m.when is not None:
                        r.when = m.when
                    if m.priority is not None:
                        r.priority = m.priority
            applied.append(f"triage: edited rule '{m.rule_id}'. {note}")
        elif m.kind == "remove_triage_rule" and m.rule_id:
            proposal.triage_rules = [r for r in proposal.triage_rules if r.rule_id != m.rule_id]
            applied.append(f"triage: removed rule '{m.rule_id}'. {note}")
        elif m.kind == "resolve_open_question" and report is not None and m.question_id:
            before = len(report.open_questions)
            report.open_questions = [q for q in report.open_questions if open_question_id(q) != m.question_id]
            if len(report.open_questions) < before:
                applied.append(f"resolved open question '{m.question_id}': {m.resolution or ''}. {note}")
    return applied
