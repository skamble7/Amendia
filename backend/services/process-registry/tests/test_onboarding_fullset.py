# tests/test_onboarding_fullset.py
"""ADR-044 (Track 1) — the onboarding wizard authors the FULL bindable element set the runtime executes:
every standard task kind + message elements (receiveTask/messageCatch) + callActivity, each producing the
right manifest Executor union member. The subProcess / event-subprocess CONTAINERS stay unbound; only the
backlog's deferred stretches are refused (via the existing registry codes) — no onboarding-only refusals.
"""
from pathlib import Path

import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    OnboardingState,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedTriageRule,
)
from app.services.onboarding import OnboardingService, TransitionError
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
_SCREEN_IN = {"type": "object", "properties": {"party": {"type": "string"}}, "required": ["party"]}
_SCREEN_OUT = {"type": "object", "properties": {"hit": {"type": "boolean"}}, "required": ["hit"]}
_SCREEN_REF = "cap.payment.screen_party@^1.0.0"


def _screen_selection(side_effect="read_only"):
    return CapabilityToolSelection(
        tool="screen_party", endpoint="http://mcp.local/mcp", transport="streamable_http",
        input_schema=_SCREEN_IN, output_schema=_SCREEN_OUT, side_effect=side_effect, idempotent=True)


@pytest.fixture
def ce_service(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    """An onboarding service pinned to common_executable (so message/call/businessRule tasks activate)."""
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


# start → Svc(serviceTask) → BR(businessRuleTask) → Recv(receiveTask) → Call(callActivity) → End
_FULL_SET = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="Svc" name="Screen"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:businessRuleTask id="BR" name="Classify" calledDecision="D"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:businessRuleTask>
    <bpmn:receiveTask id="Recv" name="Await reply"><bpmn:incoming>f3</bpmn:incoming><bpmn:outgoing>f4</bpmn:outgoing></bpmn:receiveTask>
    <bpmn:callActivity id="Call" name="Sub-pack" calledElement="callee-pack"><bpmn:incoming>f4</bpmn:incoming><bpmn:outgoing>f5</bpmn:outgoing></bpmn:callActivity>
    <bpmn:endEvent id="E"><bpmn:incoming>f5</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Svc"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Svc" targetRef="BR"/>
    <bpmn:sequenceFlow id="f3" sourceRef="BR" targetRef="Recv"/>
    <bpmn:sequenceFlow id="f4" sourceRef="Recv" targetRef="Call"/>
    <bpmn:sequenceFlow id="f5" sourceRef="Call" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""


async def _attach_and_stage(svc, bpmn, *, pack_key="fullset"):
    s = await svc.create(CreateSessionRequest(pack_key=pack_key, version="1.0.0", title="t"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=bpmn), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_screen_selection()]), owner=OWNER)
    return s


def _full_set_bindings():
    return [
        BindingInput(element_id="Svc", element_kind="serviceTask", executor_type="capability",
                     capability_ref=_SCREEN_REF, hitl_mode="none"),
        BindingInput(element_id="BR", element_kind="businessRuleTask", executor_type="capability",
                     capability_ref=_SCREEN_REF, hitl_mode="none"),
        BindingInput(element_id="Recv", element_kind="receiveTask", executor_type="message",
                     message_name="pay.reply"),
        BindingInput(element_id="Call", element_kind="callActivity", executor_type="call",
                     call_pack="callee-pack", call_version="^1.0.0",
                     input_map={"callee_in": "artifacts.hit"}, output_map={"caller_out": "callee_out"}),
    ]


# --- inventory ------------------------------------------------------------------------------------

async def test_inventory_surfaces_full_bindable_set(ce_service):
    s = await ce_service.create(CreateSessionRequest(pack_key="inv", version="1.0.0", title="t"), owner=OWNER)
    s = await ce_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_FULL_SET), owner=OWNER)
    by_id = {e.element_id: e for e in s.bpmn.bindable_elements}
    assert by_id["Svc"].category == "capability" and by_id["BR"].category == "capability"
    assert by_id["Recv"].category == "message"
    assert by_id["Call"].category == "call" and by_id["Call"].called_pack == "callee-pack"
    assert by_id["Call"].called_version == "^1.0.0"
    assert set(by_id) == {"Svc", "BR", "Recv", "Call"}


async def test_inventory_reference_fixture_full_set(ce_service):
    xml = (Path(__file__).parent / "fixtures" / "wire-repair-agentic.reference.bpmn").read_text()
    s = await ce_service.create(CreateSessionRequest(pack_key="ref2", version="1.0.0", title="t", default_domain="payment"), owner=OWNER)
    s = await ce_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=xml), owner=OWNER)
    cats = {e.category for e in s.bpmn.bindable_elements}
    assert cats == {"capability", "human"}                       # the reference's on-flow tasks
    # single-fidelity: lanes → inferred roles; the reference onboards without a projection
    assert len(s.bpmn.lanes) == 3 and s.bpmn.service_tasks       # legacy views retained
    # the isolated businessRuleTask is documented (off-flow) → not bindable
    assert "ClassifyReason" not in {e.element_id for e in s.bpmn.bindable_elements}


async def test_subprocess_container_is_not_bindable(ce_service):
    xml = f"""<bpmn:definitions {_NS}>
      <bpmn:process id="P" isExecutable="true">
        <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:subProcess id="Sub"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
          <bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>
          <bpmn:serviceTask id="Inner"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:serviceTask>
          <bpmn:endEvent id="iE"><bpmn:incoming>if2</bpmn:incoming></bpmn:endEvent>
          <bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="Inner"/>
          <bpmn:sequenceFlow id="if2" sourceRef="Inner" targetRef="iE"/>
        </bpmn:subProcess>
        <bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>
        <bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="E"/>
      </bpmn:process>
    </bpmn:definitions>"""
    s = await ce_service.create(CreateSessionRequest(pack_key="sub", version="1.0.0", title="t"), owner=OWNER)
    s = await ce_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=xml), owner=OWNER)
    ids = {e.element_id for e in s.bpmn.bindable_elements}
    assert ids == {"Inner"}                                       # the nested task binds; the container does NOT


# --- bindings — full set --------------------------------------------------------------------------

async def test_full_set_bindings_bijection_passes(ce_service):
    s = await _attach_and_stage(ce_service, _FULL_SET)
    s = await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=_full_set_bindings()), owner=OWNER)
    assert s.state == OnboardingState.BINDINGS_SET
    by_id = {b.element_id: b for b in s.bindings}
    assert by_id["Recv"].executor_type == "message" and by_id["Recv"].message_name == "pay.reply"
    assert by_id["Call"].executor_type == "call" and by_id["Call"].call_pack == "callee-pack"
    assert by_id["Call"].input_map == {"callee_in": "artifacts.hit"}
    assert by_id["BR"].executor_type == "capability"


async def test_wrong_executor_category_rejected(ce_service):
    s = await _attach_and_stage(ce_service, _FULL_SET)
    bad = _full_set_bindings()
    bad[0] = BindingInput(element_id="Svc", element_kind="serviceTask", executor_type="human",
                          role="role.x", hitl_mode="manual", hitl_role="role.x")
    with pytest.raises(TransitionError) as ei:
        await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=bad), owner=OWNER)
    assert any(e.get("field") == "executor" for e in ei.value.detail["errors"])


async def test_message_executor_rejects_hitl(ce_service):
    s = await _attach_and_stage(ce_service, _FULL_SET)
    bad = _full_set_bindings()
    bad[2] = BindingInput(element_id="Recv", element_kind="receiveTask", executor_type="message",
                          message_name="pay.reply", hitl_mode="review_after", hitl_role="role.x")
    with pytest.raises(TransitionError) as ei:
        await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=bad), owner=OWNER)
    assert any("no HITL gate" in e["message"] for e in ei.value.detail["errors"])


async def test_message_executor_requires_name(ce_service):
    s = await _attach_and_stage(ce_service, _FULL_SET)
    bad = _full_set_bindings()
    bad[2] = BindingInput(element_id="Recv", element_kind="receiveTask", executor_type="message")
    with pytest.raises(TransitionError) as ei:
        await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=bad), owner=OWNER)
    assert any(e.get("field") == "message_name" for e in ei.value.detail["errors"])


# --- manifest composition -------------------------------------------------------------------------

async def test_compose_emits_message_and_call_executors(ce_service):
    s = await _attach_and_stage(ce_service, _FULL_SET)
    s = await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=_full_set_bindings()), owner=OWNER)
    s = await ce_service.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_code", "op": "eq", "value": "AC01"})]), owner=OWNER)
    s = await ce_service.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    manifest, _descs, _regs = ce_service._compose(s)
    by_id = {b.element_id: b for b in manifest.bindings}
    assert by_id["Recv"].executor.type == "message" and by_id["Recv"].executor.message_name == "pay.reply"
    assert by_id["Recv"].hitl is None                            # no gate on a message executor
    assert by_id["Call"].executor.type == "call" and by_id["Call"].executor.pack == "callee-pack"
    assert by_id["Call"].executor.input_map == {"callee_in": "artifacts.hit"}
    assert by_id["Call"].hitl is None
    assert by_id["Svc"].executor.type == "capability"


# --- deferred-stretch refusal (existing registry code, at assemble) ------------------------------

async def test_non_interrupting_esp_refused_at_assemble(ce_service):
    # a non-interrupting event sub-process is a backlog deferral (ADR-042) — refused by the EXISTING
    # compilability code at the assemble dry-run, not silently bound.
    xml = f"""<bpmn:definitions {_NS}>
      <bpmn:process id="P" isExecutable="true">
        <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:serviceTask id="Svc"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Svc"/>
        <bpmn:sequenceFlow id="f2" sourceRef="Svc" targetRef="E"/>
        <bpmn:subProcess id="ESP" triggeredByEvent="true">
          <bpmn:startEvent id="eS" isInterrupting="false"><bpmn:errorEventDefinition/><bpmn:outgoing>ef1</bpmn:outgoing></bpmn:startEvent>
          <bpmn:serviceTask id="Handle"><bpmn:incoming>ef1</bpmn:incoming><bpmn:outgoing>ef2</bpmn:outgoing></bpmn:serviceTask>
          <bpmn:endEvent id="eE"><bpmn:incoming>ef2</bpmn:incoming></bpmn:endEvent>
          <bpmn:sequenceFlow id="ef1" sourceRef="eS" targetRef="Handle"/>
          <bpmn:sequenceFlow id="ef2" sourceRef="Handle" targetRef="eE"/>
        </bpmn:subProcess>
      </bpmn:process>
    </bpmn:definitions>"""
    s = await _attach_and_stage(ce_service, xml, pack_key="esp-defer")
    # both Svc and the ESP body Handle are bindable (Handle binds like an ordinary task)
    binds = [
        BindingInput(element_id="Svc", element_kind="serviceTask", executor_type="capability",
                     capability_ref=_SCREEN_REF, hitl_mode="none"),
        BindingInput(element_id="Handle", element_kind="serviceTask", executor_type="capability",
                     capability_ref=_SCREEN_REF, hitl_mode="none"),
    ]
    s = await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    s = await ce_service.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_code", "op": "eq", "value": "AC01"})]), owner=OWNER)
    s = await ce_service.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await ce_service.assemble(s.session_id, owner=OWNER)
    codes = {f["code"] for f in s.dry_run_report["findings"] if f["severity"] == "error"}
    assert "bpmn_event_subprocess_unsupported" in codes


# --- end-to-end: onboard a message-bearing single-fidelity pack to active ------------------------

async def test_e2e_message_pack_onboards_to_active(ce_service, pack_repo):
    # single fidelity: a serviceTask (capability) + a receiveTask (message) on the flow → active.
    xml = f"""<bpmn:definitions {_NS}>
      <bpmn:process id="P" isExecutable="true">
        <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:serviceTask id="Svc"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:receiveTask id="Recv"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:receiveTask>
        <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Svc"/>
        <bpmn:sequenceFlow id="f2" sourceRef="Svc" targetRef="Recv"/>
        <bpmn:sequenceFlow id="f3" sourceRef="Recv" targetRef="E"/>
      </bpmn:process>
    </bpmn:definitions>"""
    s = await _attach_and_stage(ce_service, xml, pack_key="msg-pack")
    binds = [
        BindingInput(element_id="Svc", element_kind="serviceTask", executor_type="capability",
                     capability_ref=_SCREEN_REF, hitl_mode="none"),
        BindingInput(element_id="Recv", element_kind="receiveTask", executor_type="message",
                     message_name="pay.reply"),
    ]
    s = await ce_service.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    s = await ce_service.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_code", "op": "eq", "value": "AC01"})]), owner=OWNER)
    s = await ce_service.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await ce_service.assemble(s.session_id, owner=OWNER)
    errs = [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]
    assert errs == [], errs
    s = await ce_service.commit(s.session_id, owner=OWNER)
    assert s.state == OnboardingState.COMPLETED
    pack = await pack_repo.get("msg-pack", "1.0.0")
    assert pack.status.value == "active"
    # the message binding survived into the committed manifest
    recv = next(b for b in pack.bindings if b.element_id == "Recv")
    assert recv.executor.type == "message" and recv.executor.message_name == "pay.reply"
    # re-run commit is a no-op
    s2 = await ce_service.commit(s.session_id, owner=OWNER)
    assert s2.state == OnboardingState.COMPLETED
