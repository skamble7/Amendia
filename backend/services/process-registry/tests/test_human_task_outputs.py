# tests/test_human_task_outputs.py
"""ADR-050 — human (and message) task outputs are first-class in onboarding, and operator-authored artifact
schemas are stageable. The runtime already consumes human-produced artifacts (the wire seed's Task_ObtainInfo
→ info_resolution); this closes the ONBOARDING gap so a wizard-authored pack can do the same.

Acceptance: a session can stage art.dining.order (authored — neither tool I/O nor trigger), bind a HUMAN task
to output `order` (art.dining.order), and a downstream capability input can be sourced from that human output —
persisted into the manifest Binding.outputs + input_map, and resolving cleanly at assemble.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CapabilityToolSelection,
    CreateSessionRequest,
    DeclareArtifactRequest,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedBindingIO,
    StagedTriageRule,
)
from app.services.onboarding import OnboardingService, TransitionError
from tests.conftest import load_sample

OWNER = "usr-owner"
_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'

# start → TakeOrder(userTask, human) → ValidateOrder(serviceTask, capability) → End
_DINEIN_BPMN = f"""<bpmn:definitions {_NS}>
  <bpmn:process id="P" isExecutable="true">
    <bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:userTask id="TakeOrder" name="Take order"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:userTask>
    <bpmn:serviceTask id="ValidateOrder" name="Validate order"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="TakeOrder"/>
    <bpmn:sequenceFlow id="f2" sourceRef="TakeOrder" targetRef="ValidateOrder"/>
    <bpmn:sequenceFlow id="f3" sourceRef="ValidateOrder" targetRef="E"/>
  </bpmn:process>
</bpmn:definitions>"""

# the validator tool reads `order` + `table` and returns a verdict — `order` is produced by the HUMAN task.
_VALIDATE_TOOL = CapabilityToolSelection(
    tool="validate_order", endpoint="http://mcp.local/mcp",
    input_schema={"type": "object", "properties": {"order": {"type": "object"}, "table": {"type": "string"}},
                  "required": ["order"]},
    output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    side_effect="read_only", idempotent=True)

_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "order_type": {"type": "string"},
        "party_size": {"type": "integer"},
        "requested_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["order_type"],
}


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def _through_bindings(svc):
    s = await svc.create(CreateSessionRequest(pack_key="dinein-adr050", version="1.0.0", title="t",
                                              default_domain="dining"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_DINEIN_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_VALIDATE_TOOL]), owner=OWNER)
    return s


async def test_declare_authored_artifact_survives_capability_restaging(svc):
    s = await svc.create(CreateSessionRequest(pack_key="dinein-authored", version="1.0.0", title="t",
                                              default_domain="dining"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_DINEIN_BPMN), owner=OWNER)
    s = await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
        artifact_key="art.dining.order", title="Order", json_schema=_ORDER_SCHEMA), owner=OWNER)
    assert [a.artifact_key for a in s.authored_artifacts] == ["art.dining.order"]

    # set_capabilities rebuilds staged_artifacts wholesale — the authored one must NOT be dropped.
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_VALIDATE_TOOL]), owner=OWNER)
    assert [a.artifact_key for a in s.authored_artifacts] == ["art.dining.order"]

    # re-declaring is an upsert (no duplicate).
    s = await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
        artifact_key="art.dining.order", title="Order v2", json_schema=_ORDER_SCHEMA), owner=OWNER)
    assert [a.artifact_key for a in s.authored_artifacts] == ["art.dining.order"]
    assert s.authored_artifacts[0].title == "Order v2"


async def test_declare_authored_artifact_rejects_bad_id_and_schema(svc):
    s = await _through_bindings(svc)
    with pytest.raises(TransitionError):
        await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
            artifact_key="dining.order", title="x", json_schema=_ORDER_SCHEMA), owner=OWNER)  # bad id
    with pytest.raises(TransitionError):
        await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
            artifact_key="art.dining.order", title="x", json_schema={"type": "string"}), owner=OWNER)  # not object


async def test_human_output_binding_rejects_unstaged_schema_ref(svc):
    s = await _through_bindings(svc)  # no authored artifact declared
    binds = [
        BindingInput(element_id="TakeOrder", element_kind="userTask", executor_type="human", role="role.server",
                     outputs=[StagedBindingIO(name="order", schema_ref="art.dining.order@^1.0.0")]),
        BindingInput(element_id="ValidateOrder", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.validate_order@^1.0.0", hitl_mode="none"),
    ]
    with pytest.raises(TransitionError) as ei:
        await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    assert "not a staged, authored, or trigger artifact" in str(ei.value)


async def test_human_output_name_must_be_unique_across_the_run(svc):
    s = await _through_bindings(svc)
    s = await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
        artifact_key="art.dining.order", title="Order", json_schema=_ORDER_SCHEMA), owner=OWNER)
    # the capability's output is named `validate_order_output`; collide the human output with it.
    binds = [
        BindingInput(element_id="TakeOrder", element_kind="userTask", executor_type="human", role="role.server",
                     outputs=[StagedBindingIO(name="validate_order_output", schema_ref="art.dining.order@^1.0.0")]),
        BindingInput(element_id="ValidateOrder", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.validate_order@^1.0.0", hitl_mode="none"),
    ]
    with pytest.raises(TransitionError) as ei:
        await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)
    assert "unique across the run" in str(ei.value)


async def test_capability_input_sources_from_human_authored_output_end_to_end(svc):
    """The acceptance: stage art.dining.order, bind the human TakeOrder to output `order`, source the
    capability's `order` input from that human output → manifest Binding.outputs + input_map, clean assemble."""
    s = await _through_bindings(svc)
    s = await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
        artifact_key="art.dining.order", title="Order", json_schema=_ORDER_SCHEMA), owner=OWNER)

    binds = [
        BindingInput(element_id="TakeOrder", element_kind="userTask", executor_type="human", role="role.server",
                     outputs=[StagedBindingIO(name="order", schema_ref="art.dining.order@^1.0.0")]),
        BindingInput(element_id="ValidateOrder", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.validate_order@^1.0.0", hitl_mode="none"),
    ]
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)

    # ADR-050 item 3: the capability's `order` input was auto-sourced from the human output (not the trigger).
    validate = next(b for b in s.bindings if b.element_id == "ValidateOrder")
    order_src = validate.input_sources["validate_order_input"]
    order_field = order_src.get("fields", {}).get("order", order_src)
    assert order_field == {"from": "artifact", "name": "order", "path": "order"} or \
        order_field == {"from": "artifact", "name": "order"}, validate.input_sources

    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_codes", "op": "intersects", "value": ["AC01"]})]),
        owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    errs = [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]
    assert errs == [], errs

    # the composed manifest: the human binding carries the declared output; art.dining.order is a pack artifact.
    manifest, _descs, regs = svc._compose(s)
    by_el = {b.element_id: b for b in manifest.bindings}
    take = by_el["TakeOrder"]
    assert [(o.name, str(o.schema_)) for o in take.outputs] == [("order", "art.dining.order@^1.0.0")]
    assert "art.dining.order@^1.0.0" in {str(a) for a in manifest.artifacts}
    assert "art.dining.order" in {r.artifact_key for r in regs}
    # …and the capability input_map resolves to the human output.
    vmap = by_el["ValidateOrder"].input_map["validate_order_input"].model_dump(by_alias=True, exclude_none=True)
    src = vmap.get("fields", {}).get("order", vmap)
    assert src.get("from") == "artifact" and src.get("name") == "order", vmap
