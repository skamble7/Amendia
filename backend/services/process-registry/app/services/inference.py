# app/services/inference.py
"""ADR-027 Phase 1 — turn a BpmnSemanticModel into (a) the BpmnInventory semantic summary and
(b) an ADVISORY InferenceDraft that pre-fills the onboarding wizard.

Nothing here is authoritative: the draft is defaults + hints the operator confirms/edits; the
staged_* fields are written only by the operator's step submissions (ADR-027). Capabilities still
need a real MCP endpoint (introspect) or a catalog reuse — inference only *labels* the slots.
Mirrors the id-suggestion shape of ``mcp_introspect`` (sanitize → ``cap.<domain>.<name>`` etc.).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from amendia_bpmn import TASK_EXECUTOR_CATEGORY, BpmnSemanticModel

from app.models.onboarding import (
    ArtifactSeed,
    CapabilityCandidate,
    InferenceAnnotation,
    InferenceDraft,
    InferredBinding,
    InferredGatewayVariable,
    InferredRole,
    SodCandidate,
)
from app.services.mcp_introspect import sanitize_name

_GATEWAY_KINDS = {"exclusiveGateway", "parallelGateway", "inclusiveGateway", "complexGateway", "eventBasedGateway"}
_CONDITION_LHS = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.]*)')

# HITL heuristics (simple + documented): side-effect/approval-ish verbs on a serviceTask hint a
# review gate; a userTask is a manual human step. The operator sets the real mode against the
# capability's side_effect (the assemble-time guard enforces the floor).
_REVIEW_VERBS = ("approve", "authoriz", "release", "apply", "execute", "notify", "send", "return")
_DRAFT_HINTS = ("draft", "prepare", "assess", "create", "obtain")
_APPROVE_HINTS = ("approve", "authoriz", "sign", "confirm")

# ADR-045 (Track 3): lane PERSONA → the HITL mode a capability task in that lane *starts* at, plus a
# role description. Matched on the lane NAME (first hit wins, so order matters: approver before analyst
# so "Ops Approver" is an approver, not an analyst). This is only a STARTING suggestion — the
# assemble-time side-effect→HITL floor still governs (a side_effectful capability is always ≥
# approve_actions regardless of lane). Falls back to the verb heuristic when the lane is unrecognized.
_LANE_INTENTS: List[tuple] = [
    (("approver", "checker", "authorizer", "authoriser"), "approve_actions",
     "Four-eyes approver — authorizes side-effectful actions before they execute."),
    (("supervisor", "manager", "escalation", "lead"), "manual",
     "Supervisor / escalation — handles escalated or exception cases."),
    (("analyst", "ops", "maker", "reviewer", "operator"), "review_after",
     "Maker / analyst — reviews and edit-approves agent output."),
    (("agent", "automation", "system", "bot", "runtime", "robot"), "none",
     "Automation / AI agent — runs autonomous capability steps."),
]


def _lane_intent(lane_name: Optional[str]) -> tuple:
    """(starting_hitl_mode, role_description) for a lane persona, or (None, None) if unrecognized."""
    nm = f" {(lane_name or '').lower()} "
    for keys, hitl, desc in _LANE_INTENTS:
        if any(k in nm for k in keys):
            return hitl, desc
    return None, None


def _condition_variable(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    m = _CONDITION_LHS.match(raw)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# BpmnInventory semantic summary (Phase 1.1)
# --------------------------------------------------------------------------- #

def build_semantic_summary(sem: BpmnSemanticModel) -> Dict[str, Any]:
    gateway_ids = {n.id for n in sem.flow_nodes if n.kind in _GATEWAY_KINDS}
    event_kinds = {"startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}
    return {
        "lanes": [{"id": l.id, "name": l.name, "member_ids": l.member_ids} for l in sem.lanes],
        "pools": [{"id": p.id, "name": p.name, "is_external": p.is_external} for p in sem.pools],
        "message_flows": [
            {"id": mf.id, "name": mf.name, "source": mf.source, "target": mf.target}
            for mf in sem.message_flows
        ],
        "events": [
            {"id": n.id, "name": n.name, "subtype": n.event_subtype, "attached_to": n.attached_to}
            for n in sem.flow_nodes if n.kind in event_kinds
        ],
        "gateway_conditions": [
            {"gateway_id": f.source, "flow_id": f.id, "variable": _condition_variable(f.condition), "raw": f.condition}
            for f in sem.sequence_flows if f.condition and f.source in gateway_ids
        ],
        "data_objects": [{"id": d.id, "name": d.name} for d in sem.data_objects],
    }


# --------------------------------------------------------------------------- #
# Inference draft (Phase 1.2)
# --------------------------------------------------------------------------- #

def infer_draft(sem: BpmnSemanticModel, domain: str) -> InferenceDraft:
    dom = sanitize_name(domain) or "payment"
    draft = InferenceDraft()

    # roles: one per named lane. lane_id → role_id / name maps drive binding role + HITL suggestions.
    lane_role: Dict[str, str] = {}
    lane_name: Dict[str, str] = {}
    for lane in sem.lanes:
        if not lane.name:
            continue
        role_id = f"role.{dom}.{sanitize_name(lane.name)}"
        lane_role[lane.id] = role_id
        lane_name[lane.id] = lane.name
        # ADR-045 (Track 3): carry the lane persona's description so the Policies step seeds role_meta.
        _, role_desc = _lane_intent(lane.name)
        draft.roles.append(InferredRole(role_id=role_id, label=lane.name, source_lane=lane.id,
                                        description=role_desc))

    # ADR-033 / ADR-044: scaffold per executable element across the FULL bindable set, routed to its
    # executor CATEGORY via the shared map (capability / human / message / call). Only CONNECTED elements
    # are scaffolded (an isolated floating task is decoration, documented not executed — matching the
    # parser's reclassification). Message/call executors have no HITL gate of their own.
    connected = {f.source for f in sem.sequence_flows} | {f.target for f in sem.sequence_flows}
    for n in sem.flow_nodes:
        category = TASK_EXECUTOR_CATEGORY.get(n.kind)
        if category is None or n.id not in connected:
            continue
        name_l = (n.name or "").lower()
        if category == "human":
            hitl = "manual"                       # userTask / manualTask default to a manual gate
        elif category == "capability":
            # ADR-045 (Track 3): the task's LANE PERSONA sets the starting HITL mode (agent→none,
            # analyst→review_after, approver→approve_actions, …); fall back to the verb heuristic when
            # the lane is unrecognized/absent. This is a *starting* mode only — the assemble-time
            # side-effect→HITL floor still governs (a side_effectful capability is always ≥ approve_actions).
            lane_hitl, _ = _lane_intent(lane_name.get(n.lane_id or ""))
            hitl = lane_hitl or ("review_after" if any(v in name_l for v in _REVIEW_VERBS) else "none")
        else:
            hitl = "none"                         # message/call — no gate
        draft.bindings.append(InferredBinding(
            element_id=n.id, element_kind=n.kind, executor_type=category,
            suggested_role=lane_role.get(n.lane_id or "") if category in ("human", "capability") else None,
            suggested_hitl_mode=hitl, source_lane=n.lane_id,
        ))

    # gateway variables: one per exclusive gateway that has a condition (dedup by gateway).
    seen_gw: set[str] = set()
    for f in sem.sequence_flows:
        node = sem.node(f.source or "")
        if not (f.condition and node and node.kind == "exclusiveGateway"):
            continue
        var = _condition_variable(f.condition)
        if var and f.source not in seen_gw:
            seen_gw.add(f.source)
            draft.gateway_variables.append(InferredGatewayVariable(gateway_id=f.source, variable=var))

    # capability candidates: each connected capability-category task (serviceTask/sendTask/
    # scriptTask/businessRuleTask) + each external message flow (ADR-033).
    for n in sem.flow_nodes:
        if TASK_EXECUTOR_CATEGORY.get(n.kind) == "capability" and n.id in connected:
            nm = sanitize_name(n.name or n.id)
            draft.capability_candidates.append(CapabilityCandidate(
                source=n.id, suggested_capability_id=f"cap.{dom}.{nm}"))
    for mf in sem.message_flows:
        nm = sanitize_name(mf.name or mf.id)
        draft.capability_candidates.append(CapabilityCandidate(
            source=mf.id, suggested_capability_id=f"cap.{dom}.{nm}"))

    # artifact seeds: data objects + message names.
    for d in sem.data_objects:
        draft.artifact_seeds.append(ArtifactSeed(
            suggested_artifact_key=f"art.{dom}.{sanitize_name(d.name or d.id)}", source=d.id))
    for mf in sem.message_flows:
        if mf.name:
            draft.artifact_seeds.append(ArtifactSeed(
                suggested_artifact_key=f"art.{dom}.{sanitize_name(mf.name)}", source=mf.id))

    # SoD candidates: a draft-ish task paired with an approve-ish task in a DIFFERENT lane.
    drafts = [n for n in sem.flow_nodes if n.name and any(h in n.name.lower() for h in _DRAFT_HINTS)]
    approvals = [n for n in sem.flow_nodes if n.name and any(h in n.name.lower() for h in _APPROVE_HINTS)]
    seen_pair: set[tuple] = set()
    for a in approvals:
        for d in drafts:
            if d.id == a.id or (d.lane_id and a.lane_id and d.lane_id == a.lane_id):
                continue
            key = tuple(sorted((d.id, a.id)))
            if key in seen_pair:
                continue
            seen_pair.add(key)
            draft.sod_candidates.append(SodCandidate(
                elements=[d.id, a.id],
                rationale=f"'{d.name}' and '{a.name}' are in different lanes — four-eyes candidate",
            ))

    # advisory annotations for constructs with no manifest home today.
    for n in sem.flow_nodes:
        if n.event_subtype == "timer" or n.kind == "boundaryEvent":
            draft.annotations.append(InferenceAnnotation(
                code="sla_escalation_hint", element_id=n.id,
                message=f"'{n.name or n.id}' ({n.kind}/{n.event_subtype or 'event'}) — SLA / escalation policy hint (not executed today)"))
        if n.event_subtype == "error":
            draft.annotations.append(InferenceAnnotation(
                code="rejection_path_hint", element_id=n.id,
                message=f"'{n.name or n.id}' error event — rejection / compensation path hint"))
        if n.kind == "businessRuleTask":
            draft.annotations.append(InferenceAnnotation(
                code="decision_capability_candidate", element_id=n.id,
                message=f"'{n.name or n.id}' business rule task — bind a decision capability (native DMN "
                        f"not evaluated; decisionRef advisory)"
                        + (f" [{n.decision_ref}]" if n.decision_ref else "")))
        if n.kind == "sendTask":
            draft.annotations.append(InferenceAnnotation(
                code="send_side_effect_hint", element_id=n.id,
                message=f"'{n.name or n.id}' send task — the bound capability performs the send "
                        f"(side_effectful → approve_actions gate)"))
    for mf in sem.message_flows:
        draft.annotations.append(InferenceAnnotation(
            code="external_integration_hint", element_id=mf.id,
            message=f"message flow '{mf.name or mf.id}' — external-system integration"))

    return draft
