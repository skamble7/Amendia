# tests/test_inference_persona.py
"""ADR-045 (Track 3) — swimlane / persona inference UX.

The lane PERSONA sets the *starting* HITL mode for a capability task (agent→none, analyst→review_after,
approver→approve_actions, supervisor→manual), falling back to the verb heuristic when the lane is
unrecognized. It is only a suggestion — the assemble-time side-effect→HITL floor still governs. Lanes also
seed a persona description, and external message flows scaffold capability slots.
"""
from pathlib import Path

import pytest

from amendia_bpmn import extract_semantics, select_process_id
from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    SetBindingsRequest,
    SetCapabilitiesRequest,
)
from app.services.inference import infer_draft
from app.services.onboarding import OnboardingService, TransitionError
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = ('xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
       'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"')
_REF = Path(__file__).parent / "fixtures" / "wire-repair-agentic.reference.bpmn"


def _lane(lid, name, node):
    return f'<bpmn:lane id="{lid}" name="{name}"><bpmn:flowNodeRef>{node}</bpmn:flowNodeRef></bpmn:lane>'


# 5 capability tasks, one per persona lane (+ one in an unrecognized lane to prove the verb fallback).
_LANES_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:laneSet id="ls">
      {_lane("La", "AI Agent Runtime", "Ta")}
      {_lane("Ln", "Ops Analyst", "Tn")}
      {_lane("Lv", "Ops Approver", "Tv")}
      {_lane("Lw", "Weird Team", "Tw")}
      {_lane("Lx", "Weird Team", "Tx")}
    </bpmn:laneSet>
    <bpmn:startEvent id="S"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Ta" name="Enrich"><bpmn:incoming>f0</bpmn:incoming><bpmn:outgoing>f1</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="Tn" name="Enrich"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="Tv" name="Enrich"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="Tw" name="Approve payment"><bpmn:incoming>f3</bpmn:incoming><bpmn:outgoing>f4</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:serviceTask id="Tx" name="Enrich"><bpmn:incoming>f4</bpmn:incoming><bpmn:outgoing>f5</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f5</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f0" sourceRef="S" targetRef="Ta"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Ta" targetRef="Tn"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Tn" targetRef="Tv"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Tv" targetRef="Tw"/>
    <bpmn:sequenceFlow id="f4" sourceRef="Tw" targetRef="Tx"/>
    <bpmn:sequenceFlow id="f5" sourceRef="Tx" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""


def _draft(bpmn):
    pid = select_process_id(bpmn)
    return infer_draft(extract_semantics(bpmn, pid), "payment")


# --- §1 lane persona → HITL -----------------------------------------------------------------------

def test_lane_persona_drives_starting_hitl():
    hitl = {b.element_id: b.suggested_hitl_mode for b in _draft(_LANES_BPMN).bindings}
    assert hitl["Ta"] == "none"                       # agent lane → autonomous
    assert hitl["Tn"] == "review_after"               # analyst / maker lane
    assert hitl["Tv"] == "approve_actions"            # approver / checker lane
    # unrecognized lane → verb heuristic fallback preserved
    assert hitl["Tw"] == "review_after"               # "Approve …" is a review verb
    assert hitl["Tx"] == "none"                       # no verb → none


def test_verb_heuristic_preserved_when_no_lanes():
    # a lane-less BPMN keeps the existing behavior exactly (regression guard).
    bpmn = f"""<bpmn:definitions {_NS}>
      <bpmn:process id="P" isExecutable="true">
        <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:serviceTask id="Notify" name="Notify ops"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:serviceTask id="Read" name="Read data"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Notify"/>
        <bpmn:sequenceFlow id="f2" sourceRef="Notify" targetRef="Read"/>
        <bpmn:sequenceFlow id="f3" sourceRef="Read" targetRef="E"/>
      </bpmn:process></bpmn:definitions>"""
    hitl = {b.element_id: b.suggested_hitl_mode for b in _draft(bpmn).bindings}
    assert hitl["Notify"] == "review_after"           # verb heuristic
    assert hitl["Read"] == "none"


# --- §1 the floor is the only hard constraint -----------------------------------------------------

@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def test_side_effect_floor_holds_over_agent_lane_suggestion(svc):
    # an agent-lane capability is SUGGESTED `none`, but if it is bound to a side-effectful capability the
    # side-effect→HITL floor rejects `none` (the lane sets a starting mode, the guard sets the floor).
    bpmn = f"""<bpmn:definitions {_NS}>
      <bpmn:process id="P" isExecutable="true">
        <bpmn:laneSet id="ls">{_lane("La", "AI Agent Runtime", "Task_Screen")}</bpmn:laneSet>
        <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:serviceTask id="Task_Screen" name="Release payment"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Task_Screen"/>
        <bpmn:sequenceFlow id="f2" sourceRef="Task_Screen" targetRef="E"/>
      </bpmn:process></bpmn:definitions>"""
    s = await svc.create(CreateSessionRequest(pack_key="floor", version="1.0.0", title="t", default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=bpmn), owner=OWNER)
    # the inference suggested `none` for this agent-lane task
    assert next(b for b in s.inferred.bindings if b.element_id == "Task_Screen").suggested_hitl_mode == "none"
    # stage a SIDE-EFFECTFUL capability + bind it with the suggested none → the floor rejects it
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[CapabilityToolSelection(
        tool="screen_party", endpoint="http://mcp.local/mcp",
        input_schema={"type": "object", "properties": {"p": {"type": "string"}}, "required": ["p"]},
        output_schema={"type": "object", "properties": {"hit": {"type": "boolean"}}, "required": ["hit"]},
        side_effect="side_effectful", idempotent=True)]), owner=OWNER)
    binding = BindingInput(element_id="Task_Screen", element_kind="serviceTask", executor_type="capability",
                           capability_ref="cap.payment.screen_party@^1.0.0", hitl_mode="none")
    with pytest.raises(TransitionError) as ei:
        await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=[binding]), owner=OWNER)
    assert any(e.get("allowed_min_mode") == "approve_actions" for e in ei.value.detail["errors"])


# --- §2 persona descriptions ----------------------------------------------------------------------

def test_input_source_suggested_by_graph_position():
    # ADR-048: an entry capability task reads the trigger; a downstream one reads its nearest upstream
    # capability task's output (position only, no domain names).
    by = {b.element_id: b for b in _draft(_LANES_BPMN).bindings}
    assert by["Ta"].suggested_input_source == {"from": "trigger"}                       # entry
    assert by["Tn"].suggested_input_source == {"from": "artifact", "element": "Ta"}      # downstream
    assert by["Tv"].suggested_input_source == {"from": "artifact", "element": "Tn"}


def test_capability_bindings_carry_suggested_capability_id():
    # Batch-2: a capability element's binding carries a suggested capability id (== the candidate join
    # key), so the wizard can pre-select it; human/message/call carry None.
    draft = _draft(_REF.read_text())
    by = {b.element_id: b for b in draft.bindings}
    cand = {c.source: c.suggested_capability_id for c in draft.capability_candidates}
    assert by["Enrich"].executor_type == "capability"
    assert by["Enrich"].suggested_capability_id == cand["Enrich"] == "cap.payment.enrich_investigation"
    assert by["ApproveRepair"].executor_type == "human"
    assert by["ApproveRepair"].suggested_capability_id is None


def test_lane_personas_seed_role_descriptions():
    draft = _draft(_LANES_BPMN)
    desc = {r.label: r.description for r in draft.roles}
    assert "approver" in (desc["Ops Approver"] or "").lower()
    assert "analyst" in (desc["Ops Analyst"] or "").lower() or "maker" in (desc["Ops Analyst"] or "").lower()
    assert "agent" in (desc["AI Agent Runtime"] or "").lower()
    assert desc["Weird Team"] is None                 # unrecognized persona → no forced description


async def test_reference_attach_carries_persona_descriptions(svc):
    xml = _REF.read_text()
    s = await svc.create(CreateSessionRequest(pack_key="ref3", version="1.0.0", title="t", default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=xml), owner=OWNER)
    by_role = {r.role_id: r.description for r in s.inferred.roles}
    assert by_role["role.payment.ops_approver"] and "approver" in by_role["role.payment.ops_approver"].lower()
    assert by_role["role.payment.ai_agent_runtime"] and "agent" in by_role["role.payment.ai_agent_runtime"].lower()


# --- §4 external message-flow scaffolding ---------------------------------------------------------

def test_external_message_flows_scaffold_capability_slots():
    draft = _draft(_REF.read_text())
    # a capability candidate per external message flow, keyed by the flow id
    cand = {c.source: c.suggested_capability_id for c in draft.capability_candidates}
    assert "mf_enrich" in cand and "mf_notify" in cand
    # the external_integration_hint annotation carries the flow name (frontend renders the slot)
    ext = [a for a in draft.annotations if a.code == "external_integration_hint"]
    assert ext and all(a.element_id for a in ext)                # keyed by the message-flow id
    assert any("fetch payment" in (a.message or "") for a in ext)  # carries the flow NAME (frontend slot)
