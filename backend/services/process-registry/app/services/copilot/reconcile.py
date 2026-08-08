# app/services/copilot/reconcile.py
"""Reconcile a CopilotProposal onto an onboarding session — deterministic code is authoritative.

The LLM proposes; this module disposes. It overlays the proposal by driving the SAME OnboardingService methods
a hand-driven session uses (set_capabilities / declare_artifact / declare_trigger / set_bindings / set_triage /
set_policies / assemble), and ENFORCES the invariants the LLM must not break — correcting the proposal and
recording every correction as provenance:

  * bijection — exactly one binding per bindable element (missing elements fall back to the inference draft);
  * the side-effect floor — a side-effectful tool is clamped up to ``approve_actions`` even if the LLM proposed
    weaker; and the capability ``min_hitl_mode`` floor;
  * ADR-051 — a capability feeding a conditional gateway takes the gateway condition's first segment as its
    output NAME (the deterministic ``inferred.suggested_output_name`` wins over the LLM);
  * ADR-050/E1 — a human task that authors data a tool consumes gets an artifact schema DERIVED from the
    consuming tool's input shape (never invented) and registered; the same output name may repeat (supersede).

Domain-neutral: nothing here knows restaurants/menus/orders — it generalizes over any BPMN + any MCP catalog.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from packaging.version import Version

from amendia_contracts.common import HitlMode, hitl_mode_at_least

from app.models.onboarding import (
    BindingInput,
    CapabilityToolSelection,
    CopilotDecision,
    CopilotMcpConfig,
    CopilotOpenQuestion,
    DeclareArtifactRequest,
    DeclareTriggerRequest,
    InferenceDraft,
    IntrospectMcpResponse,
    OnboardingSession,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedBindingIO,
    StagedGatewayVariable,
    StagedSod,
    StagedTriageRule,
)
from app.services.copilot.flowgraph import FlowGraph
from app.services.copilot.proposal import (
    CopilotProposal,
    ElementProposal,
    InputMapProposal,
    OutputProposal,
    ReadOnlyInputProposal,
)
from app.services.mcp_introspect import sanitize_name
from app.validation.type_compat import describe_mismatch, schema_at_path, schema_type_compat
from app.services.onboarding import TransitionError

logger = logging.getLogger(__name__)


class ApprovalGate(NamedTuple):
    """A four-eyes approval structure, detected deterministically from the diagram (never the LLM): the human task
    ``human`` always runs before the side-effectful capability ``side_effect`` (a guaranteed predecessor), and
    reviews the ``draft`` capability's output (the SoD-paired drafter, else the nearest consumed upstream cap)."""
    human: str
    side_effect: str
    draft: Optional[str]


def detect_approval_gates(
    *, bindable: Dict[str, Any], inferred: InferenceDraft, flow_graph: Optional[FlowGraph],
    is_side_effect: Callable[[str], bool],
) -> List[ApprovalGate]:
    """The process's four-eyes approval gates, structural + domain-neutral. A gate ``(H, S, D)`` requires:
      * ``H`` is a human task SoD-PAIRED with a drafting capability ``D`` that is guaranteed-upstream of H — this
        separation-of-duties pairing (``inferred.sod_candidates``, e.g. [DraftRepair, ApproveRepair]) is what makes
        H an *approver* of D's work, distinguishing a real approval from a mere human step upstream of a side-effect;
      * ``H`` is a GUARANTEED PREDECESSOR of the NEAREST side-effectful capability ``S`` on a path (H always runs
        before S, and no other side-effect lies strictly between them — a farther side-effect is gated transitively
        by the first, not by a second consumption of the approval).
    The SoD pairing is REQUIRED, not just preferred — without it (as for a plain worker upstream of a side-effect)
    no gate forms, so nothing is materialized spuriously. No flow graph (chat path) → no gates."""
    if flow_graph is None:
        return []
    humans = [eid for eid, inv in bindable.items() if getattr(inv, "category", None) == "human"]
    caps = {eid for eid, inv in bindable.items() if getattr(inv, "category", None) == "capability"}
    side_effects = sorted(s for s in caps if is_side_effect(s))

    def sod_drafter(h: str) -> Optional[str]:
        for sod in inferred.sod_candidates:
            if h in (sod.elements or []):
                for other in sod.elements:
                    if other != h and other in caps and flow_graph.guaranteed_predecessor(other, h):
                        return other
        return None

    def is_nearest(h: str, s: str) -> bool:
        # ``s`` is the FIRST side-effect reachable from ``h``: no other side-effect lies strictly between them
        # (h → other → s). A farther side-effect reachable only THROUGH another one is gated transitively, not by
        # a second consumption of the approval — so it forms no gate with h.
        return not any(o != s and o != h and flow_graph.can_reach(h, o) and flow_graph.can_reach(o, s)
                       for o in side_effects)

    gates: List[ApprovalGate] = []
    for h in sorted(humans):
        d = sod_drafter(h)
        if d is None:                                          # not a four-eyes approver → not an approval gate
            continue
        for s in side_effects:
            if flow_graph.guaranteed_predecessor(h, s) and is_nearest(h, s):
                gates.append(ApprovalGate(human=h, side_effect=s, draft=d))
    return gates

_ARTIFACT_VERSION = "1.0.0"
_CAP_VERSION = "1.0.0"

# The CLOSED predicate operator vocabulary (mirrors app.validation.predicates._LEAF_OPS — the strict set_triage
# transition rejects anything else). A real model tends to invent friendly operators; map the obvious synonyms
# deterministically (mirroring how HITL floors are clamped) so an invalid op is normalized or dropped, never
# reaching the strict transition. "field is present / non-empty" → exists.
_VALID_OPS = {"eq", "ne", "in", "starts_with", "intersects", "exists", "gt", "gte", "lt", "lte"}
_OP_SYNONYMS = {
    "not_empty": "exists", "non_empty": "exists", "nonempty": "exists", "notempty": "exists",
    "present": "exists", "is_present": "exists", "exists_and_not_empty": "exists", "has": "exists",
    "is_not_null": "exists", "not_null": "exists", "notnull": "exists", "is_set": "exists", "set": "exists",
    "equals": "eq", "==": "eq", "is": "eq", "eq_to": "eq",
    "not_equals": "ne", "!=": "ne", "neq": "ne", "is_not": "ne",
    "one_of": "in", "any_of": "in", "member_of": "in",
    "contains_any": "intersects", "overlaps": "intersects", "any_in": "intersects",
    "startswith": "starts_with", "prefix": "starts_with", "begins_with": "starts_with",
    "greater_than": "gt", "greater_or_equal": "gte", "less_than": "lt", "less_or_equal": "lte",
    "ge": "gte", "le": "lte",
}
_LOW_CONFIDENCE = 0.55                    # below this, a decision becomes an open question for 2b


def _hrank(mode: str) -> int:
    order = [m.value for m in (HitlMode.NONE, HitlMode.REVIEW_AFTER, HitlMode.APPROVE_RESULT,
                               HitlMode.APPROVE_ACTIONS, HitlMode.MANUAL)]
    return order.index(mode) if mode in order else 0


class Reconciler:
    def __init__(self, svc: Any, *, domain: str, mcp: CopilotMcpConfig,
                 tools: IntrospectMcpResponse, proposal: CopilotProposal,
                 owner: str, trigger_name: str = "trigger",
                 user_trigger_schema: Optional[Dict[str, Any]] = None,
                 user_triage_rules: Optional[List[StagedTriageRule]] = None,
                 flow_graph: Optional[FlowGraph] = None) -> None:
        self.svc = svc
        self.domain = domain
        self.mcp = mcp
        self.tools = tools
        self.tools_by_name = {t.name: t for t in tools.tools}
        self.proposal = proposal
        self.prop_by_el = proposal.by_element()
        self.owner = owner
        self.trigger_name = sanitize_name(trigger_name) or "trigger"
        # ADR-052: the BPMN sequence-flow graph. Present on the generate path (built from the diagram) → the
        # loop-back optionality of every from='artifact' input is decided deterministically here (authoritative,
        # overriding the LLM). None on the chat path (no diagram in hand) → the reconstructed proposal's optional
        # flags are honored as-is (a chat set_input_optional edit round-trips through them).
        self.flow_graph = flow_graph
        self._producers: Dict[str, set] = {}      # output NAME -> element_ids that produce it (built in apply())
        # ADR-052 Part D: the automation/AI lane roles a HITL gate must never carry, and the pack's human approver
        # role to reassign such a gate to. Computed from the inference draft in apply().
        self._automation_roles: set = set()
        self._human_approver: Optional[str] = None
        # The four-eyes approval gates detected structurally from the diagram (Part 1), used to derive the human
        # approver (Part 4) and to guarantee the human authors a consumed approval artifact (Part 3).
        self._approval_gates: List[ApprovalGate] = []
        # Part 3: artifact_key -> the version each re-derived human artifact was registered at (bumped when its
        # schema changed vs the registered one). Bindings reference the human artifact at this version.
        self._human_artifact_versions: Dict[str, str] = {}
        # USER-PROVIDED (generate path): the trigger schema is ground truth (no augmentation, no inference) and the
        # triage rules are applied verbatim (no permissive fallback). When None (chat path), fall back to the
        # proposal's reconstructed-from-session trigger/triage (which mutations may have edited).
        self.user_trigger_schema = user_trigger_schema
        self.user_triage_rules = user_triage_rules
        self.decisions: List[CopilotDecision] = []
        self.questions: List[CopilotOpenQuestion] = []

    # -- provenance helpers -- #
    def _llm(self, kind: str, element_id: Optional[str], summary: str, p: ElementProposal) -> None:
        self.decisions.append(CopilotDecision(kind=kind, element_id=element_id, decided_by="llm",
                                              summary=summary, rationale=p.rationale, confidence=p.confidence))
        if p.confidence < _LOW_CONFIDENCE:
            self.questions.append(CopilotOpenQuestion(
                topic=kind, element_id=element_id, confidence=p.confidence,
                question=f"Low-confidence {kind} for {element_id}: {summary} — confirm?"))

    def _det(self, kind: str, element_id: Optional[str], summary: str) -> None:
        self.decisions.append(CopilotDecision(kind=kind, element_id=element_id, decided_by="deterministic",
                                              summary=summary))

    # ------------------------------------------------------------------ #
    async def apply(self, session: OnboardingSession) -> OnboardingSession:
        sid = session.session_id
        bindable = {e.element_id: e for e in session.bpmn.bindable_elements}
        inferred = session.inferred or InferenceDraft()
        inf_by_el = {b.element_id: b for b in inferred.bindings}
        # Four-eyes is a safety invariant → deterministic. Detect the approval gates structurally (Part 1) BEFORE
        # anything LLM-derived, then derive the human approver from the gate tasks (Part 4) and use the automation
        # lane to keep a gate off the machine lane (Part D).
        self._approval_gates = detect_approval_gates(
            bindable=bindable, inferred=inferred, flow_graph=self.flow_graph,
            is_side_effect=self._is_side_effect)
        self._automation_roles, self._human_approver = self._role_topology(inferred, inf_by_el)

        # 1) stage capabilities — one per compliant tool a capability element binds
        used_tools = self._capability_tools(bindable)
        # Part 5: a tool bound to MORE THAN ONE element is usually an accidental substitution (the LLM reached for
        # the nearest capability when the MCP had no matching tool) — surface it, never auto-rebind.
        tool_elems: Dict[str, List[str]] = {}
        for eid, tool in used_tools.items():
            tool_elems.setdefault(tool, []).append(eid)
        for tool, elems in tool_elems.items():
            if len(elems) > 1:
                self.questions.append(CopilotOpenQuestion(
                    topic="tool_reuse", confidence=0.3,
                    question=f"Tool '{tool}' is used for both {' and '.join(sorted(elems))} — confirm both should "
                             f"call it (an MCP without a matching tool can make the model reuse the nearest one)."))
        session = await self._stage_capabilities(sid, used_tools)

        # map every KNOWN output name -> its artifact key (for read-only input schema_refs + human-output refs)
        out_artifact = self._output_artifact_map(bindable, inf_by_el)
        # map every KNOWN output name -> the element_ids that produce it (for loop-back optionality on from=artifact)
        self._producers = self._output_producers(bindable, inf_by_el)

        # Deterministic four-eyes floor (Part 3): for every detected approval gate, guarantee the human authors an
        # approval output that the side-effect consumes — MATERIALIZING it when the LLM omitted it — so a hollow
        # approval (empty inputs/outputs, side-effect reading the draft/trigger) can never activate. Runs first, so
        # the derivation + bindings below pick up the wiring.
        self._materialize_approval_gates(inf_by_el)
        # ADR-052: in an approval pattern the side-effect must consume the human-APPROVED output, not the
        # pre-approval draft. Rewire any remaining orphaned required human output onto its downstream draft-consumer.
        self._rewire_orphaned_human_outputs()

        # 2) derive + declare human-authored artifacts (ADR-050) from the consuming tools' input shapes. Part 3: a
        # re-derived schema that DIFFERS from the one already registered at this key is registered at a bumped minor
        # version (and referenced at it), so a same-domain re-onboard adopts the improvement instead of the commit
        # silently keeping the stale (immutable) registration.
        human_arts = self._derive_human_artifacts(bindable)
        self._human_artifact_versions = {}
        for key, (title, schema) in human_arts.items():
            version = await self._resolve_artifact_version(
                session.basics.pack_key, session.basics.version, key, schema)
            self._human_artifact_versions[key] = version
            session = await self.svc.declare_artifact(sid, DeclareArtifactRequest(
                artifact_key=key, version=version, title=title, json_schema=schema), owner=self.owner)
            bump = "" if version == _ARTIFACT_VERSION else f" (bumped to {version} — schema changed vs the registered one)"
            self._det("human_artifact", None, f"derived + registered {key}@{version} from its consuming tool input shape{bump}")

        # 3) bindings (bijection + floors + ADR-051 alignment)
        binds = [self._binding(bindable[eid], inf_by_el.get(eid), out_artifact, used_tools) for eid in bindable]
        session = await self.svc.set_bindings(sid, SetBindingsRequest(bindings=binds), owner=self.owner)

        # 4) trigger (ADR-049) — declared AFTER bindings; augmented so every trigger-sourced input resolves
        trig_key, trig_schema = self._trigger(session)
        session = await self.svc.declare_trigger(sid, DeclareTriggerRequest(
            artifact_key=trig_key, version=_ARTIFACT_VERSION, title="Process trigger",
            json_schema=trig_schema), owner=self.owner)

        # 5) triage (LLM-proposed, sanitized against the closed op enum; low-confidence/dropped → open questions)
        session = await self._set_triage(session)

        # 6) policies — gateway source-artifacts (E3: variable first-segment → the named output's artifact) +
        #    SoD candidates (deterministic, from the inference draft's four-eyes pairs).
        gvars: List[StagedGatewayVariable] = []
        for g in inferred.gateway_variables:
            first = (g.variable or "").split(".", 1)[0]
            akey = out_artifact.get(first)
            if akey:
                gvars.append(StagedGatewayVariable(gateway_id=g.gateway_id, variable=g.variable, source_artifact=akey))
                self._det("gateway", g.gateway_id, f"gateway '{g.gateway_id}' reads '{g.variable}' from {akey}")
        sods = [StagedSod(elements=s.elements) for s in inferred.sod_candidates]
        session = await self.svc.set_policies(sid, SetPoliciesRequest(
            gateway_variables=gvars, sod_policies=sods), owner=self.owner)
        if sods:
            self._det("policy", None, f"pre-populated {len(sods)} separation-of-duties pair(s) from the diagram")

        # 7) assemble → dry-run validate
        session = await self.svc.assemble(sid, owner=self.owner)
        return session

    # ------------------------------------------------------------------ #
    def _capability_tools(self, bindable: Dict[str, Any]) -> Dict[str, str]:
        """element_id -> tool name for every capability element (compliant tools only)."""
        used: Dict[str, str] = {}
        for eid, inv in bindable.items():
            p = self.prop_by_el.get(eid)
            if p is None or p.executor.type != "capability":
                continue
            tool = p.executor.capability_tool
            t = self.tools_by_name.get(tool or "")
            if t is None:
                self.questions.append(CopilotOpenQuestion(
                    topic="tool_match", element_id=eid, confidence=0.0,
                    question=f"{eid}: proposed tool '{tool}' is not in the MCP catalog — pick a tool."))
                continue
            if not t.compliance.compliant:
                self.questions.append(CopilotOpenQuestion(
                    topic="tool_match", element_id=eid, confidence=0.0,
                    question=f"{eid}: tool '{tool}' is non-compliant ({', '.join(t.compliance.reasons)}) — excluded."))
                continue
            used[eid] = tool
        return used

    async def _stage_capabilities(self, sid: str, used: Dict[str, str]) -> OnboardingSession:
        sels: List[CapabilityToolSelection] = []
        seen = set()
        for tool in used.values():
            if tool in seen:
                continue
            seen.add(tool)
            t = self.tools_by_name[tool]
            sels.append(CapabilityToolSelection(
                tool=tool, endpoint=self.mcp.endpoint, transport=self.mcp.transport, headers=self.mcp.headers,
                domain=self.domain, input_schema=t.input_schema, output_schema=t.output_schema,
                side_effect=t.suggested_side_effect,   # deterministic (ack-shape), NOT the LLM
                title=(t.description or tool)[:80], description=t.description))
            self._det("binding", None, f"staged capability for tool '{tool}' (side_effect={t.suggested_side_effect})")
        return await self.svc.set_capabilities(sid, SetCapabilitiesRequest(tools=sels), owner=self.owner)

    def _cap_ref(self, tool: str) -> str:
        return f"cap.{self.domain}.{sanitize_name(tool)}@^{_CAP_VERSION}"

    def _output_artifact_map(self, bindable: Dict[str, Any], inf_by_el: Dict[str, Any]) -> Dict[str, str]:
        """output NAME -> artifact key, across capability outputs (renamed per ADR-051) and human outputs."""
        out: Dict[str, str] = {}
        for eid, inv in bindable.items():
            p = self.prop_by_el.get(eid)
            if p is None:
                continue
            if p.executor.type == "capability" and p.executor.capability_tool in self.tools_by_name:
                tool = p.executor.capability_tool
                name = self._effective_output_name(p, tool, inf_by_el.get(eid))
                out[name] = f"art.{self.domain}.{sanitize_name(tool)}_output"
            for o in p.outputs:
                out[o.name] = f"art.{self.domain}.{o.name}"
        return out

    def _output_producers(self, bindable: Dict[str, Any], inf_by_el: Dict[str, Any]) -> Dict[str, set]:
        """output NAME -> the set of element_ids that produce it (capability outputs, renamed per ADR-051, and
        human-authored outputs). The value is the set of *producers* so loop-back optionality can ask whether ANY
        producer is a guaranteed upstream predecessor of a consumer."""
        out: Dict[str, set] = {}
        for eid, inv in bindable.items():
            p = self.prop_by_el.get(eid)
            if p is None:
                continue
            if p.executor.type == "capability" and p.executor.capability_tool in self.tools_by_name:
                name = self._effective_output_name(p, p.executor.capability_tool, inf_by_el.get(eid))
                out.setdefault(name, set()).add(eid)
            for o in p.outputs:
                out.setdefault(o.name, set()).add(eid)
        return out

    def _effective_output_name(self, p: ElementProposal, tool: str, inf: Any) -> str:
        """ADR-051: prefer the gateway-derived name (deterministic ``suggested_output_name``) → the LLM's
        ``output_name`` → ``<tool>_output``. This MUST match what ``_binding`` sets."""
        gw = inf.suggested_output_name if inf else None
        if gw:
            return gw
        return (p.output_name or "").strip() or f"{sanitize_name(tool)}_output"

    # -- deterministic four-eyes (Part 1/3/4) -- #
    def _is_side_effect(self, eid: str) -> bool:
        """True iff the proposal binds ``eid`` to a side-effectful tool (ack-shape, deterministic — not the LLM)."""
        p = self.prop_by_el.get(eid)
        tool = self.tools_by_name.get(p.executor.capability_tool or "") if p and p.executor.type == "capability" else None
        return bool(tool and tool.suggested_side_effect == "side_effectful")

    def _element_output_name(self, eid: str, inf_by_el: Dict[str, Any]) -> Optional[str]:
        """The output NAME an element produces (capability: ADR-051 effective name; human: its first output)."""
        p = self.prop_by_el.get(eid)
        if p is None:
            return None
        if p.executor.type == "capability" and p.executor.capability_tool in self.tools_by_name:
            return self._effective_output_name(p, p.executor.capability_tool, inf_by_el.get(eid))
        return p.outputs[0].name if p.outputs else None

    def _element_role(self, eid: str, inf_by_el: Dict[str, Any]) -> Optional[str]:
        """The role a human element carries — the LLM's proposed role, else the lane-derived inferred role."""
        p = self.prop_by_el.get(eid)
        if p and p.executor.type == "human" and p.executor.role:
            return p.executor.role
        b = inf_by_el.get(eid)
        return b.suggested_role if b else None

    def _materialize_approval_gates(self, inf_by_el: Dict[str, Any]) -> None:
        """Deterministic backstop for four-eyes. For every detected gate (H, S, D): if H already authors an output S
        consumes, leave it (the LLM did it right); otherwise MATERIALIZE the approval — ensure H authors a
        human-authored output A (synthesized from the draft/element ids if the LLM gave none), repoint S onto A (the
        field(s) that read the draft D, else the single unmapped object input of S's tool), and give H the draft as
        read-only review context. So ``_derive_human_artifacts`` derives A's schema from S's tool input (never
        invents fields) and the side-effect is gated by the approval. If S has no unambiguous field for A, wire what
        is safe and raise a HIGH-VISIBILITY open question — never let an approval gate activate hollow."""
        for gate in self._approval_gates:
            hp, sp = self.prop_by_el.get(gate.human), self.prop_by_el.get(gate.side_effect)
            if hp is None or sp is None:
                continue
            h_outputs = {o.name for o in hp.outputs if o.human_authored}
            if any(m.from_ == "artifact" and m.name in h_outputs for m in sp.input_map):
                continue                                             # S already consumes an approval output of H
            d_out = self._element_output_name(gate.draft, inf_by_el) if gate.draft else None
            a_name = next(iter(sorted(h_outputs)), None)             # reuse H's existing human output if any
            if a_name is None:
                a_name = f"approved_{d_out}" if d_out else f"{sanitize_name(gate.human)}_output"
                hp.outputs.append(OutputProposal(name=a_name, human_authored=True))
                self._det("dataflow", gate.human,
                          f"materialized human-authored output '{a_name}' — {gate.human} gates the side-effect "
                          f"{gate.side_effect} but the design left the approval hollow")
            # wire S to consume A: prefer repointing the draft-reading field(s), else the single unmapped object field
            wired = False
            if d_out:
                for m in sp.input_map:
                    if m.from_ == "artifact" and m.name == d_out:
                        m.name = a_name
                        wired = True
                if wired:
                    self._det("dataflow", gate.side_effect,
                              f"{gate.side_effect} now consumes the approved '{a_name}' from {gate.human}, not the "
                              f"pre-approval draft '{d_out}' (four-eyes gate)")
            if not wired:
                wired = self._wire_single_object_field(gate.side_effect, sp, a_name)
            # H reviews the draft as read-only context
            if d_out and not any(ri.source_output == d_out for ri in hp.read_only_inputs):
                hp.read_only_inputs.append(ReadOnlyInputProposal(name=f"{d_out}_review", source_output=d_out))
            if not wired:
                self.questions.append(CopilotOpenQuestion(
                    topic="approval_gate", element_id=gate.side_effect, confidence=0.0,
                    question=f"{gate.human} approves before the side-effect {gate.side_effect}, but {gate.side_effect} "
                             f"has no clear input for the approved result — materialized '{a_name}'; confirm which "
                             f"input of {gate.side_effect} should consume it."))

    def _wire_single_object_field(self, s_eid: str, sp: ElementProposal, a_name: str) -> bool:
        """Wire ``a_name`` onto S's single UNMAPPED object-typed tool input (the corrected/authored value), if
        exactly one exists — otherwise leave it for the open question (never invent/guess which field)."""
        tool = self.tools_by_name.get(sp.executor.capability_tool or "")
        if tool is None or not isinstance(tool.input_schema, dict):
            return False
        props = tool.input_schema.get("properties", {}) or {}
        mapped = {m.field for m in sp.input_map}
        obj_fields = [f for f, sub in props.items()
                      if f not in mapped and isinstance(sub, dict) and sub.get("type") == "object"]
        if len(obj_fields) != 1:
            return False
        sp.input_map.append(InputMapProposal(field=obj_fields[0], **{"from": "artifact"}, name=a_name))
        self._det("dataflow", s_eid, f"{s_eid} now consumes the approved '{a_name}' on its '{obj_fields[0]}' input")
        return True

    # -- human-authored artifact derivation (ADR-050) -- #
    def _rewire_orphaned_human_outputs(self) -> None:
        """An approval pattern (agent drafts D → human approves → side-effect applies) requires the side-effect to
        consume the human-APPROVED output X, not the pre-approval draft D. A REQUIRED human output that NOTHING
        consumes is a wiring error: the approval doesn't gate execution, and Part C has no consumer to derive X's
        schema from (empty form). When the human reviewed exactly one draft D (a read-only input) and a step
        downstream of the approval consumes D, rewire that consumer onto X — so the approval gates execution AND X's
        schema derives concretely. If the correct consumer is ambiguous, leave it and raise a low-confidence open
        question — UNLESS the output is a TERMINAL recorded decision (its task is not an approval gate and has no
        downstream side-effect it could gate, e.g. an SLA-breach escalation): a terminal record is legitimately
        unconsumed, so it neither flags nor blocks go-live (its schema is still registered for the refiner). Needs
        the flow graph (generate path) to tell 'downstream'; domain-neutral."""
        if self.flow_graph is None:
            return

        def references(name: str) -> bool:
            return any(
                any(m.from_ == "artifact" and m.name == name for m in c.input_map)
                or any(ri.source_output == name for ri in c.read_only_inputs)
                for c in self.prop_by_el.values())

        gate_humans = {g.human for g in self._approval_gates}
        side_effect_elems = [e for e in self.prop_by_el if self._is_side_effect(e)]

        for eid, p in self.prop_by_el.items():
            if p.executor.type != "human":
                continue
            for o in p.outputs:
                if not o.human_authored or references(o.name):
                    continue                                   # not a human output, or already consumed
                drafts = [ri.source_output for ri in p.read_only_inputs]
                d = drafts[0] if len(drafts) == 1 else None    # the single reviewed draft, else ambiguous
                targets = [cid for cid in self.prop_by_el
                           if d and cid != eid and self.flow_graph.can_reach(eid, cid)
                           and any(m.from_ == "artifact" and m.name == d for m in self.prop_by_el[cid].input_map)]
                if targets:
                    for cid in targets:
                        for m in self.prop_by_el[cid].input_map:
                            if m.from_ == "artifact" and m.name == d:
                                m.name = o.name                # draft → approved output
                        self._det("dataflow", cid, f"{cid} now consumes the approved '{o.name}' from {eid}, not the "
                                                   f"pre-approval draft '{d}' (four-eyes gate)")
                    continue
                # a terminal recorded decision — not an approval gate, and no downstream side-effect it could gate
                # (e.g. an SLA-breach escalation) — is legitimately unconsumed: don't flag it or block go-live.
                is_terminal = (eid not in gate_humans
                               and not any(self.flow_graph.can_reach(eid, s) for s in side_effect_elems))
                if is_terminal:
                    self._det("dataflow", eid, f"'{o.name}' from {eid} is a terminal recorded decision — no "
                                               f"downstream consumer needed (its schema is registered for review)")
                else:
                    self.questions.append(CopilotOpenQuestion(
                        topic="dataflow", element_id=eid, confidence=0.2,
                        question=f"Nothing consumes {eid}'s output '{o.name}' — which downstream step should consume "
                                 f"the approved result?"))

    def _derive_human_artifacts(self, bindable: Dict[str, Any]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
        """For each human-authored output name X, derive a CLOSED object schema from the fields the consuming tools
        read from it (never invent a field the tool doesn't consume). So the HITL Form renders real typed fields
        (not Raw JSON), the derived schema is kept as CONCRETE as the consumers declare and UNIONED across all of
        them: a whole-object read contributes that tool field's declared sub-properties (with their types / enums /
        nested items), a by-path read contributes the single sub-field it reads. When several steps consume X (one
        reads the whole object, another reads X.field by path) every referenced field ends up present. A consumer
        that types the field as an opaque object contributes nothing concrete — an inherent limit — but a well-typed
        input is never stripped down to a bare object.

        ADR-054 (extended): the tool-derived props above are AUTHORITATIVE (a consumed field keeps its tool typing +
        stays required). On top of them the LLM's proposed BASELINE ``fields`` (the human's form) are UNIONED in —
        so an artifact no tool consumes isn't an empty form. Derived wins on a name conflict (never let a baseline
        guess override a concrete consumed field); a baseline-only field is optional by default (a draft to refine).
        The tool input-map over-map guard is untouched — baseline fields live only on the human's artifact."""
        # output name -> the human OutputProposal (for its baseline fields), keeping the first author of each name
        authored: Dict[str, Any] = {}
        for p in self.prop_by_el.values():
            for o in p.outputs:
                if o.human_authored:
                    authored.setdefault(o.name, o)
        result: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        for name in sorted(authored):
            derived: Dict[str, Any] = {}                          # AUTHORITATIVE — what tools actually consume
            for p in self.prop_by_el.values():
                if p.executor.type != "capability":
                    continue
                tool = self.tools_by_name.get(p.executor.capability_tool or "")
                if tool is None or not isinstance(tool.input_schema, dict):
                    continue
                tprops = tool.input_schema.get("properties", {}) or {}
                for m in p.input_map:
                    if m.name != name or m.from_ != "artifact":
                        continue
                    field_schema = tprops.get(m.field)
                    if field_schema is None:
                        continue
                    if m.path:                                     # X.<path> read → that one sub-field, typed
                        derived[m.path] = self._merge_field(derived.get(m.path), field_schema)
                    elif isinstance(field_schema, dict):           # whole-object read → union its declared props
                        for k, v in (field_schema.get("properties") or {}).items():
                            derived[k] = self._merge_field(derived.get(k), v)

            baseline, baseline_required = self._baseline_props(authored[name])
            # ADR-057: field-level union — the tool-derived TYPE stays authoritative (a scalar the tool consumes is
            # never upgraded to an object by a baseline guess), but where the tool typed a field as an UNDER-SPECIFIED
            # object/array/enum (an opaque `{type:object}`, a bare-item array, a string with no enum) we adopt the
            # LLM baseline's nested `properties`/`items`/`enum` so the HITL form renders real sub-fields, not a raw
            # editor. A baseline-only field is carried through as-is.
            props: Dict[str, Any] = dict(baseline)
            for k, dv in derived.items():
                props[k] = self._fill_opaque(dv, baseline[k]) if k in baseline else dv
            required = set(derived) | {f for f in baseline_required if f not in derived}
            key = f"art.{self.domain}.{name}"
            seeded = sorted(f for f in baseline if f not in derived)   # fields that came only from the LLM baseline
            if seeded:
                self._det("human_artifact", None, f"seeded a baseline schema for {key} ({', '.join(seeded)}) from "
                                                  f"process context — copilot draft, review in the refiner")
            result[key] = (name.replace("_", " ").title(), self._closed_object(props, required))
        return result

    @staticmethod
    def _baseline_props(o: Any) -> Tuple[Dict[str, Any], set]:
        """The LLM's proposed baseline form fields for a human-authored output → (props, required-names). Domain-
        neutral: scalars / enum / simple object+array, mirroring what the schema refiner renders."""
        props: Dict[str, Any] = {}
        required: set = set()
        for f in (getattr(o, "fields", None) or []):
            if not f.name:
                continue
            props[f.name] = Reconciler._field_schema(f)
            if f.required:
                required.add(f.name)
        return props, required

    @staticmethod
    def _field_schema(f: Any) -> Dict[str, Any]:
        """One baseline OutputFieldProposal → a concrete draft-2020-12 field schema."""
        t = (f.type or "string").lower()
        if f.enum:
            s: Dict[str, Any] = {"type": "string", "enum": list(f.enum)}
        elif t == "object":
            sub = {c.name: Reconciler._field_schema(c) for c in (f.properties or []) if c.name}
            s = {"type": "object", "properties": sub, "additionalProperties": False}
        elif t == "array":
            s = {"type": "array", "items": {"type": (f.items or "string")}}
        elif t in ("string", "number", "integer", "boolean"):
            s = {"type": t}
        else:
            s = {"type": "string"}
        if f.title:
            s["title"] = f.title
        if f.description:
            s["description"] = f.description
        return s

    @staticmethod
    def _merge_field(existing: Optional[Dict[str, Any]], incoming: Any) -> Dict[str, Any]:
        """Union two candidate schemas for the SAME property across consumers, preferring the one carrying more
        concrete typing (properties / enum / items / type / format) so a well-typed declaration is never lost to an
        opaque one."""
        inc = copy.deepcopy(incoming) if isinstance(incoming, dict) else {}
        if not isinstance(existing, dict):
            return inc

        def richness(s: Any) -> int:
            return sum(1 for k in ("properties", "enum", "items", "type", "format")
                       if isinstance(s, dict) and s.get(k) is not None)

        return inc if richness(inc) > richness(existing) else existing

    @staticmethod
    def _fill_opaque(derived: Any, baseline: Any) -> Dict[str, Any]:
        """ADR-057: keep the tool-DERIVED field's declared type authoritative, but when the tool left it under-
        specified, borrow the LLM BASELINE's nested shape. Only fills gaps, never overrides the tool's type:
        - an object with no/empty ``properties`` adopts the baseline's ``properties`` (when the baseline is an object)
        - an array with no/opaque ``items`` adopts the baseline's ``items``
        - a string with no ``enum`` adopts the baseline's ``enum``
        A tool field the baseline can't concretise (e.g. tool says scalar, baseline says object) is returned as-is."""
        if not isinstance(derived, dict):
            return copy.deepcopy(baseline) if isinstance(baseline, dict) else {}
        out = copy.deepcopy(derived)
        if not isinstance(baseline, dict):
            return out
        t = out.get("type")
        if t == "object" and not (isinstance(out.get("properties"), dict) and out["properties"]):
            bp = baseline.get("properties")
            if isinstance(bp, dict) and bp:
                out["properties"] = copy.deepcopy(bp)
                if isinstance(baseline.get("required"), list) and "required" not in out:
                    out["required"] = list(baseline["required"])
        if t == "array" and not (isinstance(out.get("items"), dict) and out["items"]):
            bi = baseline.get("items")
            if isinstance(bi, dict) and bi:
                out["items"] = copy.deepcopy(bi)
        if t in ("string", None) and "enum" not in out and isinstance(baseline.get("enum"), list):
            out["enum"] = list(baseline["enum"])
        return out

    @staticmethod
    def _closed_object(props: Dict[str, Any], required: Optional[set] = None) -> Dict[str, Any]:
        """A closed object schema. ``required`` is explicit (tool-consumed fields required; baseline-only fields per
        their proposed flag, defaulting to optional); when omitted, every prop is required (legacy: consumed-only)."""
        req = sorted(required) if required is not None else sorted(props.keys())
        return {"type": "object", "properties": props, "additionalProperties": False,
                "required": req,
                "$schema": "https://json-schema.org/draft/2020-12/schema"}

    async def _resolve_artifact_version(
        self, pack_key: str, pack_version: str, key: str, schema: Dict[str, Any]
    ) -> str:
        """The version to register a re-derived artifact schema at. Nothing registered at this key yet → 1.0.0. An
        already-registered version carries an IDENTICAL schema → reuse it (unchanged schemas don't churn). Otherwise
        the schema changed → bump the minor above the highest registered version, so a same-domain re-onboard adopts
        the improvement (the commit keeps same key+version immutable, so a differing body must go to a new version).

        ADR-060: reads are scoped to the pack being built (a pack only sees its own owned schemas)."""
        regs = await self.svc.schemas.list_by_key(pack_key, pack_version, key)
        if not regs:
            return _ARTIFACT_VERSION
        for r in regs:
            if r.json_schema == schema:
                return r.version                          # identical to a registered version → reuse, no bump
        latest = max(regs, key=lambda r: Version(r.version))
        return self._bump_minor(latest.version)

    @staticmethod
    def _bump_minor(version: str) -> str:
        v = Version(version)
        return f"{v.major}.{v.minor + 1}.0"

    def _artifact_ref_version(self, artifact_key: str) -> str:
        """The version to reference a human artifact at (the bumped one if its schema changed, else 1.0.0)."""
        return self._human_artifact_versions.get(artifact_key, _ARTIFACT_VERSION)

    # -- one binding, with all invariants enforced -- #
    def _binding(self, inv: Any, inf: Any, out_artifact: Dict[str, str], used: Dict[str, str]) -> BindingInput:
        eid = inv.element_id
        p = self.prop_by_el.get(eid)
        category = inv.category                       # capability | human | message | call (BPMN-fixed)
        etype = category
        b = BindingInput(element_id=eid, element_kind=inv.element_kind, executor_type=etype, hitl_mode="none")

        if category == "capability":
            tool = used.get(eid) or (p.executor.capability_tool if p else None)
            if tool and tool in self.tools_by_name:
                b.capability_ref = self._cap_ref(tool)
                side_effect = self.tools_by_name[tool].suggested_side_effect
                # ADR-051 output name: gateway alignment (deterministic) wins over the LLM
                gw_name = inf.suggested_output_name if inf else None
                if gw_name:
                    b.output_name = gw_name
                    self._det("output_name", eid, f"named output '{gw_name}' to satisfy the gateway condition it feeds")
                elif p and p.output_name:
                    b.output_name = p.output_name.strip()
                    self._llm("output_name", eid, f"named output '{b.output_name}'", p)
                # HITL: LLM proposal clamped up to the side-effect floor
                b.hitl_mode, b.hitl_role = self._clamp_hitl(eid, p, side_effect, inf)
                # input_map (LLM proposal → composite over the tool input fields); refine fills any gaps
                b.input_sources = self._capability_input_sources(eid, tool, p)
                if p:
                    self._llm("binding", eid, f"bound {eid} → tool '{tool}'", p)
            return b

        if category == "human":
            role = (p.executor.role if p and p.executor.role else None) or (inf.suggested_role if inf else None) or f"role.{self.domain}.human"
            b.role = role
            b.hitl_mode = (p.hitl.mode if p and p.hitl.mode != "none" else "manual")
            b.hitl_role = (p.hitl.role if p and p.hitl.role else role)
            # authored outputs (ADR-050) — referenced at the version they were registered at (Part 3 bump-aware)
            b.outputs = [StagedBindingIO(
                name=o.name,
                schema_ref=f"art.{self.domain}.{o.name}@^{self._artifact_ref_version(f'art.{self.domain}.{o.name}')}",
                required=True) for o in (p.outputs if p else [])]
            # read-only context inputs (ADR-048 for human tasks)
            ro_inputs: List[StagedBindingIO] = []
            ro_sources: Dict[str, Any] = {}
            for ri in (p.read_only_inputs if p else []):
                akey = out_artifact.get(ri.source_output)
                if not akey:
                    self.questions.append(CopilotOpenQuestion(
                        topic="read_only_input", element_id=eid, confidence=0.3,
                        question=f"{eid}: read-only input '{ri.name}' sources unknown output '{ri.source_output}'."))
                    continue
                ro_inputs.append(StagedBindingIO(name=ri.name, schema_ref=f"{akey}@^{self._artifact_ref_version(akey)}", required=False))
                src: Dict[str, Any] = {"from": "artifact", "name": ri.source_output}
                # ADR-048: a human read-only input from a branch/loop-back producer is absent-tolerant too — mark it
                # optional so the normal path (the branch didn't run) resolves instead of hard-failing input_unresolved.
                optional = bool(ri.optional) if self.flow_graph is None else self._source_is_loopback(eid, ri.source_output, ri.name)
                if optional:
                    src["optional"] = True
                ro_sources[ri.name] = src
            b.inputs = ro_inputs
            b.input_sources = ro_sources
            if p:
                summary = f"human ({role})" + (f", authors {[o.name for o in p.outputs]}" if p.outputs else "")
                self._llm("binding", eid, f"bound {eid} → {summary}", p)
            return b

        if category == "message":
            b.message_name = (p.executor.message_name if p and p.executor.message_name else None) or inv.message_name
            return b

        # call
        b.call_pack = (p.executor.call if p and p.executor.call else None) or getattr(inv, "called_pack", None)
        b.call_version = getattr(inv, "called_version", None) or "^1.0.0"
        return b

    def _clamp_hitl(self, eid: str, p: Optional[ElementProposal], side_effect: str, inf: Any) -> Tuple[str, Optional[str]]:
        proposed = (p.hitl.mode if p else None) or (inf.suggested_hitl_mode if inf else None) or "none"
        floor = "none"
        if side_effect == "side_effectful":
            floor = HitlMode.APPROVE_ACTIONS.value
        role = (p.hitl.role if p and p.hitl.role else None) or (inf.suggested_role if inf else None)
        if not hitl_mode_at_least(proposed, floor):
            self._det("hitl", eid, f"clamped HITL '{proposed}' up to the side-effect floor '{floor}'")
            proposed = floor
        elif p:
            self._llm("hitl", eid, f"HITL mode '{proposed}'", p)
        # a HITL gate is a HUMAN authorization: its role must be a human lane, never the automation/AI lane that
        # executes the step (no human holds that role, so the gate could never be authorized).
        if proposed != "none":
            role = self._humanize_gate_role(eid, role)
            if not role:                                          # still unassigned → a generic human reviewer
                role = f"role.{self.domain}.reviewer"
        return proposed, (role if proposed != "none" else None)

    def _humanize_gate_role(self, eid: str, role: Optional[str]) -> Optional[str]:
        """Guard: if a HITL gate's role is the automation/AI lane's own role (structurally, a lane whose bindable
        members are all capability tasks), reassign it to the pack's human approver — the role its human approval
        tasks use. If that's unambiguous, use it + record provenance; if none/ambiguous, leave the gate (so the
        control isn't lost) but raise a low-confidence open question for the operator to answer."""
        if not role or role not in self._automation_roles:
            return role
        if self._human_approver:
            self._det("hitl", eid, f"reassigned the approval gate from the automation lane role '{role}' to the "
                                   f"human approver '{self._human_approver}' — a machine lane can't authorize a gate")
            return self._human_approver
        self.questions.append(CopilotOpenQuestion(
            topic="hitl", element_id=eid, confidence=0.2,
            question=f"{eid}: this side-effectful step needs human approval, but the diagram assigns it to the "
                     f"automation lane and no single human approver role was found — who authorizes this action?"))
        return role                                               # leave the gate; the open question flags it

    def _role_topology(self, inferred: InferenceDraft, inf_by_el: Dict[str, Any]) -> Tuple[set, Optional[str]]:
        """Compute (automation_lane_roles, human_approver_role). The automation lane is structural: a lane whose
        bindable members are ALL capability tasks. The human approver is derived STRUCTURALLY from the detected
        approval-gate tasks (Part 4) — real approval user-tasks are ``manual`` gates, so keying on an approve HITL
        mode misses them. The role(s) on the gate tasks H: one distinct → use it; several → the one gating the most
        side-effects (ties → ambiguous); no gates → fall back to an approve-mode human role, then the sole human
        role, else ambiguous (None → the gate raises the open question)."""
        approve = {HitlMode.APPROVE_RESULT.value, HitlMode.APPROVE_ACTIONS.value}
        lane_execs: Dict[str, set] = {}
        for b in inferred.bindings:
            if b.source_lane:
                lane_execs.setdefault(b.source_lane, set()).add(b.executor_type)
        automation_lanes = {lane for lane, execs in lane_execs.items() if execs == {"capability"}}
        automation_roles = {b.suggested_role for b in inferred.bindings
                            if b.source_lane in automation_lanes and b.suggested_role}
        automation_roles |= {r.role_id for r in inferred.roles
                             if r.source_lane in automation_lanes and r.role_id}

        # Part 4: the approver is the role on the human tasks that gate a side-effect (weighted by how many).
        gate_role_counts: Dict[str, int] = {}
        for g in self._approval_gates:
            role = self._element_role(g.human, inf_by_el)
            if role and role not in automation_roles:
                gate_role_counts[role] = gate_role_counts.get(role, 0) + 1
        human_approver: Optional[str] = None
        if len(gate_role_counts) == 1:
            human_approver = next(iter(gate_role_counts))
        elif gate_role_counts:
            top = max(gate_role_counts.values())
            leaders = [r for r, c in gate_role_counts.items() if c == top]
            human_approver = leaders[0] if len(leaders) == 1 else None   # tie → ambiguous
        else:
            # no gates detected → the legacy heuristics (approve-mode human role, then the sole human role)
            human_roles = {b.suggested_role for b in inferred.bindings
                           if b.executor_type == "human" and b.suggested_role} - automation_roles
            approver_roles = {b.suggested_role for b in inferred.bindings
                              if b.executor_type == "human" and b.suggested_role
                              and b.suggested_hitl_mode in approve} - automation_roles
            if len(approver_roles) == 1:
                human_approver = next(iter(approver_roles))
            elif len(human_roles) == 1:
                human_approver = next(iter(human_roles))
        return automation_roles, human_approver

    def _capability_input_sources(self, eid: str, tool: str, p: Optional[ElementProposal]) -> Dict[str, Any]:
        if not p or not p.input_map:
            return {}                                 # let set_bindings' E3 refine derive them
        # OVER-MAP GUARD (deterministic; the LLM proposes, deterministic code disposes — like the HITL clamp): a
        # tool's input schema is CLOSED, so mapping a field the tool doesn't declare fails at runtime
        # (MCP_TOOL_ERROR). Keep only fields that are declared properties of THIS tool's introspected input schema.
        t = self.tools_by_name.get(tool)
        declared = set((t.input_schema or {}).get("properties", {}) or {}) if t and isinstance(t.input_schema, dict) else set()
        fields: Dict[str, Any] = {}
        for m in p.input_map:
            if declared and m.field not in declared:
                self._det("input_map", eid, f"dropped input '{m.field}' — not accepted by '{tool}' (its input "
                                            f"schema doesn't declare it)")
                continue
            src: Dict[str, Any] = {"from": m.from_}
            if m.name:
                src["name"] = m.name
            if m.path:
                src["path"] = m.path
            if self._is_optional_source(eid, m):
                src["optional"] = True            # ADR-048: absent-tolerant (loop-back / branch producer)
            # TYPE-COMPAT GUARD (ADR-052 follow-up): the name is declared, but a mapped source whose JSON TYPE
            # can't satisfy the tool field's declared type still fails at runtime (isError → MCP_TOOL_ERROR —
            # the wire "Screen" hold). Warn so the operator repoints it; the commit validator hard-rejects it.
            # Only trigger-sourced fields are checkable here (the trigger schema is in hand); artifact sources
            # and a missing schema degrade to no-op (schema_type_compat → unknown).
            tgt = (t.input_schema.get("properties") or {}).get(m.field) if declared else None
            if tgt is not None and m.from_ == "trigger" and isinstance(self.user_trigger_schema, dict):
                src_schema = schema_at_path(self.user_trigger_schema, m.path or m.field)
                if schema_type_compat(src_schema, tgt) == "incompatible":
                    detail = describe_mismatch(src_schema, tgt) or "type mismatch"
                    self._det("input_map", eid, f"type-incompatible input '{m.field}' ← trigger "
                                                f"'{m.path or m.field}': {detail}")
                    self.questions.append(CopilotOpenQuestion(
                        topic="input_map", element_id=eid, confidence=0.0,
                        question=(f"'{eid}' input '{m.field}' ← trigger '{m.path or m.field}': {detail}. The tool "
                                  f"'{tool}' will reject this shape at runtime — map a type-compatible source "
                                  f"(e.g. a scalar leaf) or drop the field.")))
            fields[m.field] = src
        return {f"{sanitize_name(tool)}_input": {"fields": fields}} if fields else {}

    def _is_optional_source(self, eid: str, m: Any) -> bool:
        """AUTHORITATIVE loop-back optionality for one input field (ADR-048/052). A from='artifact' field is
        REQUIRED iff at least one producer of the named output is a *guaranteed predecessor* of ``eid`` (lies on
        every path from start to eid and eid can't loop back to it). Otherwise — every producer runs on a loop-back
        relative to eid, only on a subset of branches, or the output has no known producer — the field is OPTIONAL
        so a first-pass resolution (before the loop produces it) omits it instead of hard-failing input_unresolved.

        from='trigger'/'seed' sources are always present → never optional. This overrides any LLM-proposed flag.
        On the chat path (no flow graph in hand) the reconstructed proposal's own ``optional`` is honored verbatim
        (a conversational set_input_optional edit round-trips through it)."""
        if m.from_ != "artifact":
            return False                          # trigger/seed inputs are always present
        if self.flow_graph is None:
            return bool(m.optional)               # chat path: honor the flag the proposal/mutation carries
        return self._source_is_loopback(eid, m.name, m.field)

    def _source_is_loopback(self, eid: str, source_name: Optional[str], field_label: str) -> bool:
        """The core loop-back decision, keyed on ``(eid, source output name)`` and shared by capability input maps
        AND human read-only inputs. A from='artifact' source is loop-back/branch OPTIONAL iff NO producer of
        ``source_name`` is a *guaranteed predecessor* of ``eid`` (on every path from start to eid, with no loop
        back). Records the same provenance. Requires the flow graph — callers handle the chat path themselves."""
        producers = self._producers.get(source_name or "", set())
        if any(self.flow_graph.guaranteed_predecessor(prod, eid) for prod in producers):
            return False
        producer_txt = ", ".join(sorted(producers)) or "no upstream step"
        self._det("input_map", eid, f"marked input '{field_label}' optional — its source '{source_name}' is produced "
                                    f"by loop-back/branch step {producer_txt}, not guaranteed upstream of {eid}")
        return True

    # -- trigger + triage -- #
    def _trigger(self, session: OnboardingSession) -> Tuple[str, Dict[str, Any]]:
        key = f"art.{self.domain}.{self.trigger_name}"
        if self.user_trigger_schema is not None:
            # Generate: the user provided the trigger CONTRACT — register it verbatim. No augmentation (inventing
            # fields would corrupt the user's contract); trigger-sourced maps were grounded on this in the prompt.
            # Register it OPEN as authored — never force-close it: a trigger validates the fields the pack consumes,
            # it must not reject a real event that carries extras (that is the ADR-047 `envelope_invalid` bug).
            schema = copy.deepcopy(self.user_trigger_schema)
            schema.setdefault("type", "object")
            schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
            self.decisions.append(CopilotDecision(kind="trigger", element_id=None, decided_by="user",
                                  summary="registered the user-provided trigger schema"))
            return key, schema
        # Chat / legacy: the proposal's (reconstructed) trigger schema, augmented so trigger-sourced maps resolve.
        # Kept OPEN for the same reason — extras are allowed; the trigger only validates what the pack reads.
        schema = copy.deepcopy(self.proposal.trigger_schema) if isinstance(self.proposal.trigger_schema, dict) else {"type": "object"}
        schema.setdefault("type", "object")
        props = dict(schema.get("properties", {}))
        for b in session.bindings:
            for src in (b.input_sources or {}).values():
                self._collect_trigger_paths(src, props)
        schema["properties"] = props
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        return key, schema

    def _collect_trigger_paths(self, src: Any, props: Dict[str, Any]) -> None:
        if not isinstance(src, dict):
            return
        if src.get("fields"):
            for sub in src["fields"].values():
                self._collect_trigger_paths(sub, props)
        elif src.get("from") == "trigger":
            top = (src.get("path") or "").split(".", 1)[0]
            if top and top not in props:
                props[top] = {"type": "string"}       # a permissive default so the reference resolves

    def _sanitize_when(self, when: Any, tfields: set) -> Optional[Dict[str, Any]]:
        """Normalize + validate a predicate tree against the CLOSED op enum and the trigger fields. Synonyms map
        deterministically (not_empty → exists); an op that still isn't valid, a field not on the trigger, or a
        comparison op with no value → the node is dropped (None). Returns a strict-transition-safe predicate."""
        if not isinstance(when, dict):
            return None
        for junction in ("all", "any"):
            if junction in when:
                subs = [s for s in (self._sanitize_when(x, tfields) for x in (when[junction] or [])) if s]
                return {junction: subs} if subs else None
        if "not" in when:
            inner = self._sanitize_when(when["not"], tfields)
            return {"not": inner} if inner else None
        if "field" in when and "op" in when:
            field = when.get("field")
            op = str(when.get("op") or "").strip().lower()
            op = _OP_SYNONYMS.get(op, op)
            if op not in _VALID_OPS or not isinstance(field, str) or not field:
                return None
            if tfields and field.split(".", 1)[0] not in tfields:
                return None                      # a field not on the trigger would fail the strict field check
            if op == "exists":
                return {"field": field, "op": op}    # exists takes no value (drops a stray null that trips the check)
            value = when.get("value")
            if value is None:
                return None                      # a comparison op needs a value — can't be made valid → drop
            return {"field": field, "op": op, "value": value}
        return None

    def _fallback_triage(self, tfields: set) -> Optional[StagedTriageRule]:
        """A guaranteed-valid, permissive triage rule for when nothing else survives: the trigger's discriminator
        field must EXIST. ``exists`` is valid for every JSON type and the field is a declared trigger field, so the
        strict transition accepts it. Domain-neutral — prefers a ``…type`` discriminator, else the first field."""
        if not tfields:
            return None
        field = next((f for f in sorted(tfields) if f.endswith("type")), sorted(tfields)[0])
        return StagedTriageRule(rule_id="auto_trigger_match", priority=100, when={"field": field, "op": "exists"})

    async def _set_triage(self, session: OnboardingSession) -> OnboardingSession:
        sid = session.session_id
        tfields = {k.split(".", 1)[0] for k in (session.trigger_fields or {})}
        rules: List[StagedTriageRule] = []

        if self.user_triage_rules is not None:
            # Generate: the USER authored these rules — apply them VERBATIM. The predicate sanitation still runs as a
            # safety net (normalizes a synonym op, drops a broken node → open question), but there is NO permissive
            # fallback here — the operator owns triage, so an empty/invalid set surfaces rather than being invented.
            for r in self.user_triage_rules:
                san = self._sanitize_when(r.when, tfields) if r.when else None
                if san is None:
                    self._det("triage", None, f"dropped user triage rule '{r.rule_id}' — its predicate wasn't valid "
                                              f"against the trigger schema")
                    self.questions.append(CopilotOpenQuestion(
                        topic="triage", confidence=0.0,
                        question=f"Your triage rule '{r.rule_id}' didn't validate against the trigger — please "
                                 f"re-check its field/operator."))
                    continue
                rules.append(StagedTriageRule(rule_id=r.rule_id, priority=r.priority,
                                              description=r.description, when=san))
                self.decisions.append(CopilotDecision(kind="triage", element_id=None, decided_by="user",
                                      summary=f"applied user triage rule '{r.rule_id}'"))
            return await self.svc.set_triage(sid, SetTriageRequest(triage_rules=rules), owner=self.owner)

        # Chat / legacy: proposal-carried rules (reconstructed from the session, possibly edited by a chat mutation)
        # → sanitize; if nothing survives, a permissive trigger-field fallback keeps the draft valid.
        for r in self.proposal.triage_rules:
            san = self._sanitize_when(r.when, tfields) if r.when else None
            if san is None:
                self._det("triage", None, f"dropped triage rule '{r.rule_id}' — its predicate used an unsupported "
                                          f"operator or a field not on the trigger")
                self.questions.append(CopilotOpenQuestion(
                    topic="triage", confidence=0.0,
                    question=f"I couldn't derive a reliable triage rule from '{r.rule_id}' — please confirm which "
                             f"incoming events this process should handle."))
                continue
            rules.append(StagedTriageRule(rule_id=r.rule_id, priority=r.priority, description=r.description, when=san))
            self.decisions.append(CopilotDecision(kind="triage", decided_by="llm",
                                  summary=f"proposed triage rule '{r.rule_id}'", rationale=r.rationale, confidence=r.confidence))
            if r.confidence < _LOW_CONFIDENCE:
                self.questions.append(CopilotOpenQuestion(topic="triage", confidence=r.confidence,
                                      question=f"Triage rule '{r.rule_id}' is the least diagram-derivable — confirm the predicate."))

        if not rules:
            fb = self._fallback_triage(tfields)
            if fb is not None:
                rules.append(fb)
                self._det("triage", None, "no reliable triage predicate survived — added a permissive trigger-field "
                                          "match so the draft stays valid")
                self.questions.append(CopilotOpenQuestion(
                    topic="triage", confidence=0.0,
                    question="I couldn't derive a reliable triage rule — please confirm which incoming events this "
                             "process should handle."))

        try:
            return await self.svc.set_triage(sid, SetTriageRequest(triage_rules=rules), owner=self.owner)
        except TransitionError:
            fb = self._fallback_triage(tfields)
            if fb is None:
                raise
            self.questions.append(CopilotOpenQuestion(
                topic="triage", confidence=0.0,
                question="I couldn't derive a valid triage rule — please confirm which incoming events this "
                         "process should handle."))
            return await self.svc.set_triage(sid, SetTriageRequest(triage_rules=[fb]), owner=self.owner)
