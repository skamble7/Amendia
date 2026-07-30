# tests/test_human_task_inputs.py
"""ADR-048 for HUMAN tasks — a human (userTask) binding may declare INPUTS (an input_map from upstream-produced
outputs) it reads as read-only context, mirroring how ADR-050 lets it declare OUTPUTS. This is the ONBOARDING
side of "give a manual HITL form on-screen context": e.g. a diner's Select-items task sees the menu (produced
upstream by a Present-menu capability) while choosing.

The manifest contract (Binding.inputs + Binding.input_map) and the pack validator's stage-5 upstream-production
check are already GENERAL (not capability-gated), so this needs no new backend code — these tests assert the
existing machinery already carries a human binding's declared inputs into the manifest and validates them:
  * an input mapped from an UPSTREAM capability output assembles clean through the 7-stage validator;
  * an input mapped from a NON-upstream (unproduced) output is rejected with the existing `binding_input_unproduced`.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedBindingIO,
    StagedTriageRule,
)
from app.services.onboarding import OnboardingService
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'

# start → PresentMenu(serviceTask, capability) → SelectItems(userTask, human) → End
_MENU_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="PresentMenu" name="Present menu"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:userTask id="SelectItems" name="Select items"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:userTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="PresentMenu"/>
    <bpmn:sequenceFlow id="f2" sourceRef="PresentMenu" targetRef="SelectItems"/>
    <bpmn:sequenceFlow id="f3" sourceRef="SelectItems" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""

# get_menu: a read-only capability that produces the menu the human reads. Its output is mirrored to
# art.dining.get_menu_output (name get_menu_output) — the source the human input references.
_MENU_TOOL = CapabilityToolSelection(
    tool="get_menu", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"ticket_id": {"type": "string"}}},
    output_schema={"type": "object",
                   "properties": {"sections": {"type": "array", "items": {"type": "object"}}},
                   "required": ["sections"]},
    side_effect="read_only", idempotent=True)


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def _through_caps(svc):
    s = await svc.create(CreateSessionRequest(pack_key="dinein-inputs", version="1.0.0", title="t",
                                              default_domain="dining"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_MENU_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_MENU_TOOL]), owner=OWNER)
    return s


def _binds(menu_source):
    """PresentMenu (capability) → SelectItems (human, reads `menu` from `menu_source`, no output)."""
    return [
        BindingInput(element_id="PresentMenu", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.get_menu@^1.0.0", hitl_mode="none"),
        BindingInput(element_id="SelectItems", element_kind="userTask", executor_type="human", role="role.server",
                     inputs=[StagedBindingIO(name="menu", schema_ref="art.dining.get_menu_output@^1.0.0")],
                     input_sources={"menu": menu_source}),
    ]


async def _assemble_errors(svc, s):
    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1,
                         when={"field": "reason_codes", "op": "intersects", "value": ["AC01"]})]), owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    return s, [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]


async def test_human_input_from_upstream_capability_output_assembles_and_validates(svc):
    # A human binding declares an input `menu` sourced from the UPSTREAM PresentMenu capability's output.
    s = await _through_caps(svc)
    s = await svc.set_bindings(
        s.session_id,
        SetBindingsRequest(bindings=_binds({"from": "artifact", "name": "get_menu_output"})), owner=OWNER)

    # set_bindings stored the human binding's declared input + its ADR-048 source (not capability-gated).
    select = next(b for b in s.bindings if b.element_id == "SelectItems")
    assert [(io.name, io.schema_ref.split("@", 1)[0]) for io in select.inputs] == [("menu", "art.dining.get_menu_output")]
    assert select.input_sources["menu"] == {"from": "artifact", "name": "get_menu_output"}

    # the 7-stage validator passes: the input's source IS produced upstream (PresentMenu → get_menu_output).
    s, errs = await _assemble_errors(svc, s)
    assert errs == [], errs

    # …and the composed manifest carries the human binding's inputs + input_map through to Binding.
    manifest, _descs, _regs = svc._compose(s)
    by_el = {b.element_id: b for b in manifest.bindings}
    sel = by_el["SelectItems"]
    assert [(io.name, str(io.schema_)) for io in sel.inputs] == [("menu", "art.dining.get_menu_output@^1.0.0")]
    src = sel.input_map["menu"].model_dump(by_alias=True, exclude_none=True)
    assert src.get("from") == "artifact" and src.get("name") == "get_menu_output", src


async def test_human_input_from_non_upstream_output_is_rejected(svc):
    # The SAME shape, but the input is sourced from an output NO upstream task produces → the existing stage-5
    # check rejects it (binding_input_unproduced) — human bindings are validated just like capability ones.
    s = await _through_caps(svc)
    s = await svc.set_bindings(
        s.session_id,
        SetBindingsRequest(bindings=_binds({"from": "artifact", "name": "not_produced_anywhere"})), owner=OWNER)

    s, errs = await _assemble_errors(svc, s)
    codes = {e.get("code") for e in errs}
    assert "binding_input_unproduced" in codes, errs
