# tests/test_gateway_output_naming.py
"""ADR-051 — a capability binding's OUTPUT NAME is settable and DEFAULTED from the gateway it feeds, so
wizard-onboarded gateways branch. The runtime resolves a gateway condition against binding output names
(``validation.order_verdict`` needs an output literally named ``validation``), but introspection forces
``<tool>_output`` — so the two never match and the gateway silently never branches. Here the output auto-names
``validation`` (from the fed gateway's condition), an operator can override it, and a task feeding no gateway
keeps ``<tool>_output``.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    SetBindingsRequest,
    SetCapabilitiesRequest,
)
from app.services.onboarding import OnboardingService
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'

# start → ValidateOrder(serviceTask) → Gateway_OrderOK(exclusiveGateway, branches on validation.order_verdict)
_GW_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="ValidateOrder" name="Validate order"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:exclusiveGateway id="Gateway_OrderOK"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f_ok</bpmn:outgoing><bpmn:outgoing>f_bad</bpmn:outgoing></bpmn:exclusiveGateway>
    <bpmn:endEvent id="E_ok"><bpmn:incoming>f_ok</bpmn:incoming></bpmn:endEvent>
    <bpmn:endEvent id="E_bad"><bpmn:incoming>f_bad</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="ValidateOrder"/>
    <bpmn:sequenceFlow id="f2" sourceRef="ValidateOrder" targetRef="Gateway_OrderOK"/>
    <bpmn:sequenceFlow id="f_ok" sourceRef="Gateway_OrderOK" targetRef="E_ok"><bpmn:conditionExpression>validation.order_verdict == "ok"</bpmn:conditionExpression></bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="f_bad" sourceRef="Gateway_OrderOK" targetRef="E_bad"><bpmn:conditionExpression>validation.order_verdict != "ok"</bpmn:conditionExpression></bpmn:sequenceFlow>
  </bpmn:process>
</bpmn:definitions>"""

# ValidateOrder → End — no gateway downstream (the output keeps its <tool>_output default).
_NOGW_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="ValidateOrder" name="Validate order"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="ValidateOrder"/>
    <bpmn:sequenceFlow id="f2" sourceRef="ValidateOrder" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""

_VALIDATE_TOOL = CapabilityToolSelection(
    tool="validate_order", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"order": {"type": "object"}}, "required": ["order"]},
    output_schema={"type": "object", "properties": {"order_verdict": {"type": "string"}}, "required": ["order_verdict"]},
    side_effect="read_only", idempotent=True)


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def _bind(svc, bpmn, output_name=None):
    s = await svc.create(CreateSessionRequest(pack_key="gw", version="1.0.0", title="t", default_domain="dining"),
                         owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=bpmn), owner=OWNER)
    inferred = s
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_VALIDATE_TOOL]), owner=OWNER)
    b = BindingInput(element_id="ValidateOrder", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.validate_order@^1.0.0", hitl_mode="none", output_name=output_name)
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=[b]), owner=OWNER)
    return inferred, s


async def test_capability_output_auto_names_from_fed_gateway(svc):
    inferred, s = await _bind(svc, _GW_BPMN)
    # inference suggests the gateway-condition first segment as the output name…
    vb_inf = next(b for b in inferred.inferred.bindings if b.element_id == "ValidateOrder")
    assert vb_inf.suggested_output_name == "validation"
    # …and set_bindings applies it as the default (NOT validate_order_output), keeping the schema_ref.
    vb = next(b for b in s.bindings if b.element_id == "ValidateOrder")
    assert [o.name for o in vb.outputs] == ["validation"]
    assert vb.outputs[0].schema_ref.split("@", 1)[0] == "art.dining.validate_order_output"


async def test_operator_output_name_overrides_the_gateway_default(svc):
    _inferred, s = await _bind(svc, _GW_BPMN, output_name="verdict")
    vb = next(b for b in s.bindings if b.element_id == "ValidateOrder")
    assert [o.name for o in vb.outputs] == ["verdict"]


async def test_capability_not_feeding_a_gateway_keeps_tool_output(svc):
    inferred, s = await _bind(svc, _NOGW_BPMN)
    assert next(b for b in inferred.inferred.bindings if b.element_id == "ValidateOrder").suggested_output_name is None
    vb = next(b for b in s.bindings if b.element_id == "ValidateOrder")
    assert [o.name for o in vb.outputs] == ["validate_order_output"]
