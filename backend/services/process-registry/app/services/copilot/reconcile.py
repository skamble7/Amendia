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
from typing import Any, Dict, List, Optional, Tuple

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
from app.services.copilot.proposal import CopilotProposal, ElementProposal
from app.services.mcp_introspect import sanitize_name
from app.services.onboarding import TransitionError

logger = logging.getLogger(__name__)

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
                 user_triage_rules: Optional[List[StagedTriageRule]] = None) -> None:
        self.svc = svc
        self.domain = domain
        self.mcp = mcp
        self.tools = tools
        self.tools_by_name = {t.name: t for t in tools.tools}
        self.proposal = proposal
        self.prop_by_el = proposal.by_element()
        self.owner = owner
        self.trigger_name = sanitize_name(trigger_name) or "trigger"
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

        # 1) stage capabilities — one per compliant tool a capability element binds
        used_tools = self._capability_tools(bindable)
        session = await self._stage_capabilities(sid, used_tools)

        # map every KNOWN output name -> its artifact key (for read-only input schema_refs + human-output refs)
        out_artifact = self._output_artifact_map(bindable, inf_by_el)

        # 2) derive + declare human-authored artifacts (ADR-050) from the consuming tools' input shapes
        human_arts = self._derive_human_artifacts(bindable)
        for key, (title, schema) in human_arts.items():
            session = await self.svc.declare_artifact(sid, DeclareArtifactRequest(
                artifact_key=key, version=_ARTIFACT_VERSION, title=title, json_schema=schema), owner=self.owner)
            self._det("human_artifact", None, f"derived + registered {key} from its consuming tool input shape")

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

    def _effective_output_name(self, p: ElementProposal, tool: str, inf: Any) -> str:
        """ADR-051: prefer the gateway-derived name (deterministic ``suggested_output_name``) → the LLM's
        ``output_name`` → ``<tool>_output``. This MUST match what ``_binding`` sets."""
        gw = inf.suggested_output_name if inf else None
        if gw:
            return gw
        return (p.output_name or "").strip() or f"{sanitize_name(tool)}_output"

    # -- human-authored artifact derivation (ADR-050) -- #
    def _derive_human_artifacts(self, bindable: Dict[str, Any]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
        """For each human-authored output name X, derive a CLOSED object schema from the fields the consuming
        tools read from it (never invent a field the tool doesn't consume)."""
        # collect human-authored output names
        authored = {o.name for p in self.prop_by_el.values() for o in p.outputs if o.human_authored}
        result: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        for name in sorted(authored):
            whole: Optional[Dict[str, Any]] = None
            props: Dict[str, Any] = {}
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
                    if m.path:
                        props[m.path] = copy.deepcopy(field_schema)
                    else:
                        whole = copy.deepcopy(field_schema)
            schema = self._close_object(whole, props)
            result[f"art.{self.domain}.{name}"] = (name.replace("_", " ").title(), schema)
        return result

    @staticmethod
    def _close_object(whole: Optional[Dict[str, Any]], extra_props: Dict[str, Any]) -> Dict[str, Any]:
        base: Dict[str, Any] = copy.deepcopy(whole) if isinstance(whole, dict) and whole.get("type") == "object" else {"type": "object"}
        base.setdefault("type", "object")
        props = dict(base.get("properties", {}))
        props.update(extra_props)
        base["properties"] = props
        base["additionalProperties"] = False
        base["required"] = sorted(props.keys())
        base["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        return base

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
            # authored outputs (ADR-050)
            b.outputs = [StagedBindingIO(name=o.name, schema_ref=f"art.{self.domain}.{o.name}@^{_ARTIFACT_VERSION}",
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
                ro_inputs.append(StagedBindingIO(name=ri.name, schema_ref=f"{akey}@^{_ARTIFACT_VERSION}", required=False))
                ro_sources[ri.name] = {"from": "artifact", "name": ri.source_output}
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
        # a gated capability needs a role
        if proposed != "none" and not role:
            role = f"role.{self.domain}.reviewer"
        return proposed, (role if proposed != "none" else None)

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
            fields[m.field] = src
        return {f"{sanitize_name(tool)}_input": {"fields": fields}} if fields else {}

    # -- trigger + triage -- #
    def _trigger(self, session: OnboardingSession) -> Tuple[str, Dict[str, Any]]:
        key = f"art.{self.domain}.{self.trigger_name}"
        if self.user_trigger_schema is not None:
            # Generate: the user provided the trigger CONTRACT — register it verbatim. No augmentation (inventing
            # fields would corrupt the user's contract); trigger-sourced maps were grounded on this in the prompt.
            schema = copy.deepcopy(self.user_trigger_schema)
            schema.setdefault("type", "object")
            schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
            schema.setdefault("additionalProperties", False)
            self.decisions.append(CopilotDecision(kind="trigger", element_id=None, decided_by="user",
                                  summary="registered the user-provided trigger schema"))
            return key, schema
        # Chat / legacy: the proposal's (reconstructed) trigger schema, augmented so trigger-sourced maps resolve.
        schema = copy.deepcopy(self.proposal.trigger_schema) if isinstance(self.proposal.trigger_schema, dict) else {"type": "object"}
        schema.setdefault("type", "object")
        props = dict(schema.get("properties", {}))
        for b in session.bindings:
            for src in (b.input_sources or {}).values():
                self._collect_trigger_paths(src, props)
        schema["properties"] = props
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        schema.setdefault("additionalProperties", False)
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
