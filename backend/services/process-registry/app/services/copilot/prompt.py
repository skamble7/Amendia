# app/services/copilot/prompt.py
"""Build the single grounded prompt for the copilot's semantic call.

The prompt carries the deterministic substrate (BPMN inventory + tool catalog + inference hints) and the rules
the proposal must obey, then asks for ONE JSON object matching the CopilotProposal shape. Domain-neutral — every
line is generic; the model reads business meaning off the diagram + tool descriptions, never off hardcoded nouns.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from amendia_bpmn.semantics import BpmnSemanticModel
from app.models.onboarding import InferenceDraft, IntrospectMcpResponse

_SYSTEM = """\
You are Amendia's onboarding copilot. You turn a BPMN process diagram plus a catalog of MCP tools into a complete,
runnable process-pack configuration. A deterministic engine handles the mechanics and will CORRECT or override any
choice of yours that breaks a rule — so aim for a valid, faithful result; do not fight the rules.

Decide, for the diagram, all of:
- executor per bindable element: a serviceTask usually binds an MCP tool (capability); a userTask is a human;
  a receive/message element is a message; a callActivity is a call.
- HITL oversight per gate: none | review_after | approve_result | approve_actions | manual, plus the role (lane).
  A gate is a HUMAN authorization — its role must be a HUMAN lane (an approver/reviewer), NEVER the automation/AI
  lane that executes the step (no human holds that role, so the gate could never be authorized). For a
  side-effectful agent step, put approve_actions on the human approver, not the agent.
- output names: name a capability output so a gateway condition that reads it (a condition `<output>.<field>`)
  resolves — the output name MUST equal the condition's first segment, and its artifact must carry that field.
- input maps: map each tool input field to an upstream artifact/field — whole artifact (by output name), a scalar
  by name, or a path into an object; or from the trigger. If a mapped artifact is produced by a step that only
  runs on a LOOP-BACK (after this element, then loops in) or on just one branch, that field isn't guaranteed to
  exist on the first pass — mark it `optional: true` so it's omitted rather than failing. (The engine decides this
  from the diagram authoritatively, so a wrong guess is corrected — but flag the obvious loop-back inputs.)
- human-authored outputs: a human task that produces data a downstream tool consumes (name the output); its schema
  is derived from the consuming tool's input shape, so you only NAME it (set human_authored: true). A required human
  output MUST be consumed by a downstream step — never leave it orphaned.
- approval pattern (agent DRAFTS an artifact → human APPROVES it → a side-effect APPLIES it): the side-effect and
  every downstream step must consume the human-APPROVED output, NEVER the pre-approval draft — otherwise the
  approval doesn't gate execution. Map the apply/downstream input from the human's output, not the draft.
- read-only human inputs: upstream artifacts a human step should see as on-form context.

You do NOT invent the trigger or the triage — the USER provides those. A trigger schema is given to you as ground
truth; use its ACTUAL fields for any trigger-sourced input.

RULES the proposal must obey (the engine enforces these; a violation is clamped or dropped, not accepted):
1. Exactly one binding per bindable element (bijection).
2. A side-effectful tool ⇒ HITL at least `approve_actions`.
3. A binding's HITL must be at least the capability's minimum.
4. A conditional gateway's condition first segment must equal an upstream output NAME whose artifact carries that
   (required) decision field (ADR-051).
5. Human tasks may author outputs (ADR-050) and read upstream artifacts read-only.
6. Every input_map source must be produced upstream or come from the trigger/seed.
7. The same human output name may repeat across tasks only if it is the SAME artifact (revise-loop supersede).
8. A capability input_map may map ONLY fields that are DECLARED PROPERTIES of that tool's input schema — never a
   field the tool doesn't declare (its schema is closed; extra fields fail at runtime). Map only what the tool reads.
9. A trigger-sourced input (`from:"trigger"`) MUST reference a field that exists in the provided trigger schema
   (use its real path — do not invent nested paths).

Respond with a SINGLE JSON object only — no markdown, no prose, no code fences.
"""

# A compact shape guide for the CopilotProposal JSON (clearer for the model than the raw JSON Schema dump).
_SHAPE = """\
Return JSON of this shape:
{
  "summary": "one plain-language paragraph describing the process end to end",
  "elements": [
    {
      "element_id": "<bpmn id>",
      "executor": {"type": "capability|human|message|call",
                   "capability_tool": "<tool name if capability>",
                   "role": "role.<domain>.<lane> if human",
                   "message_name": "<if message>", "call": "<callee pack if call>"},
      "hitl": {"mode": "none|review_after|approve_result|approve_actions|manual", "role": "role.<domain>.<lane>"},
      "output_name": "<capability output rename = the gateway condition's first segment — else omit>",
      "outputs": [{"name": "<human output name>", "human_authored": true}],
      "input_map": [{"field": "<tool input field — MUST be a declared property of this tool's input schema>",
                     "from": "artifact|trigger",
                     "name": "<upstream output name if artifact>",
                     "path": "<if from trigger: a real field of the provided trigger schema>",
                     "optional": "<true if the source runs on a loop-back/branch and may be absent first pass>"}],
      "read_only_inputs": [{"name": "<binding input name>", "source_output": "<upstream output name>"}],
      "confidence": 0.0-1.0, "rationale": "one line"
    }
  ]
}
Include EVERY bindable element exactly once. Omit fields that don't apply. Do NOT emit a trigger schema or triage
rules — those are user-provided.
"""


def _lane_name_by_element(sem: BpmnSemanticModel) -> Dict[str, Optional[str]]:
    lane_name = {ln.id: (ln.name or ln.id) for ln in sem.lanes}
    out: Dict[str, Optional[str]] = {}
    for n in sem.flow_nodes:
        out[n.id] = lane_name.get(n.lane_id) if n.lane_id else None
    return out


def _bpmn_inventory(sem: BpmnSemanticModel) -> Dict[str, Any]:
    lane_of = _lane_name_by_element(sem)
    elements = [
        {"id": n.id, "name": n.name, "kind": n.kind, "lane": lane_of.get(n.id),
         **({"documentation": n.documentation} if n.documentation else {}),
         **({"event_subtype": n.event_subtype} if n.event_subtype else {}),
         **({"attached_to": n.attached_to} if n.attached_to else {})}
        for n in sem.flow_nodes
    ]
    gateways = [
        {"source": f.source, "target": f.target, "name": f.name, "condition": f.condition}
        for f in sem.sequence_flows if f.condition
    ]
    lanes = [{"id": ln.id, "name": ln.name, "members": ln.member_ids} for ln in sem.lanes]
    return {"process_id": sem.process_id, "lanes": lanes, "elements": elements,
            "gateway_conditions": gateways,
            "message_flows": [{"source": m.source, "target": m.target, "name": m.name} for m in sem.message_flows]}


def _tool_catalog(tools: IntrospectMcpResponse) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tools.tools:
        out.append({
            "name": t.name, "description": t.description,
            "input_schema": t.input_schema, "output_schema": t.output_schema,
            "side_effect": t.suggested_side_effect, "compliant": t.compliance.compliant,
            "suggested_capability_id": t.suggested_capability_id,
        })
    return out


def _hints(inferred: Optional[InferenceDraft]) -> Dict[str, Any]:
    if inferred is None:
        return {}
    return {
        "roles_by_lane": [{"role_id": r.role_id, "lane": r.source_lane} for r in inferred.roles],
        "capability_candidates": [c.source for c in inferred.capability_candidates],
        "gateway_variables": [{"gateway_id": g.gateway_id, "variable": g.variable}
                              for g in inferred.gateway_variables],
        "suggested": [
            {"element_id": b.element_id, "executor_type": b.executor_type,
             "suggested_role": b.suggested_role, "suggested_capability_id": b.suggested_capability_id,
             "suggested_output_name": b.suggested_output_name, "suggested_hitl_mode": b.suggested_hitl_mode,
             "upstream_producers": b.upstream_producers}
            for b in inferred.bindings
        ],
        "sod_candidates": [{"elements": s.elements, "rationale": s.rationale} for s in inferred.sod_candidates],
    }


_CHAT_SYSTEM = """\
You are Amendia's onboarding copilot in REVIEW mode. A draft process pack already exists; the operator refines it
one plain-language message at a time. You NEVER write pack JSON directly — you translate the message into a small,
closed set of TYPED MUTATIONS that a deterministic engine then applies and re-validates (it enforces the same
safety floors, so a request to remove a required control is honored only up to the floor, and you say so).

If the message is ambiguous, or references something not in the draft, DO NOT GUESS: set needs_clarification=true,
emit NO mutations, and ask a short clarifying question in `reply`.

The closed mutation vocabulary (emit only these `kind`s; each carries a one-line `rationale`):
- set_hitl {element_id, mode?, role?}
- set_executor {element_id, capability_tool | role(human) | message_name | call}
- set_input_map_field {element_id, field, source:{from:"artifact|trigger", name?, path?, optional?}}
- remove_input_map_field {element_id, field}
- set_input_optional {element_id, input, field, optional}   (mark a loop-back/not-guaranteed input absent-tolerant)
- set_output_name {element_id, output?, new_name}
- add_read_only_input {element_id, name, source_output}
- remove_read_only_input {element_id, name}
- set_side_effect {tool, side_effect}          (re-triggers the HITL floor deterministically)
- edit_trigger {trigger_field, trigger_type?, trigger_remove?}
- add_triage_rule {rule_id, when, priority?} / edit_triage_rule {rule_id, when?, priority?} / remove_triage_rule {rule_id}
- resolve_open_question {question_id, resolution}

Rules the mutations must respect (the engine clamps violations): a side-effectful tool stays at HITL >=
approve_actions; a binding's HITL stays >= the capability minimum; a gateway condition's first segment must equal an
upstream output name carrying that field; input sources must be produced upstream or come from the trigger.

Respond with a SINGLE JSON object only — {reply, needs_clarification, mutations:[...]} — no markdown, no fences.
"""


def build_chat_messages(
    *, proposal_json: Dict[str, Any], report_json: Dict[str, Any],
    open_question_ids: List[str], conversation: List[Dict[str, str]],
    tool_names: List[str], message: str,
) -> List[Dict[str, str]]:
    """The two-message chat prompt: the review-mode system framing + a user turn carrying the current draft, the
    report (summary + open questions with their ids), the recent conversation, the tool catalog, and the message."""
    context = {
        "current_draft": proposal_json,
        "report": report_json,
        "open_question_ids": open_question_ids,
        "available_tools": tool_names,
        "recent_conversation": conversation[-6:],
    }
    user = (f"Current draft + context:\n{json.dumps(context, default=str)}\n\n"
            f"Operator message:\n{message}\n\n"
            "Return the CopilotEdit JSON (reply + needs_clarification + mutations).")
    return [{"role": "system", "content": _CHAT_SYSTEM}, {"role": "user", "content": user}]


def build_messages(
    *, sem: BpmnSemanticModel, tools: IntrospectMcpResponse,
    inferred: Optional[InferenceDraft], domain: str, trigger_schema: Dict[str, Any],
) -> List[Dict[str, str]]:
    """The two-message prompt: a system framing (role + rules + shape) and a user turn carrying the grounded
    inventory + tool catalog + deterministic hints + the USER-PROVIDED trigger schema (ground truth)."""
    payload = {
        "domain": domain,
        "bpmn": _bpmn_inventory(sem),
        "tools": _tool_catalog(tools),
        "trigger_schema": trigger_schema,      # user-provided ground truth — trigger-sourced input_map fields MUST use these
        "deterministic_hints": _hints(inferred),
    }
    user = (
        "Here is the diagram, the MCP tool catalog, the USER-PROVIDED trigger schema (ground truth for any "
        "trigger-sourced input), and the deterministic engine's hints. Produce the CopilotProposal JSON.\n\n"
        f"{json.dumps(payload, default=str)}\n\n{_SHAPE}"
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
