# tests/test_refine_artifact.py
"""ADR-054 Part C — refine a human-authored artifact's schema on the onboarding session.

The refined schema (typed props, JSON-Schema ``title`` labels, enums) persists on authored_artifacts; the version
is resolved server-side (bump-on-change vs the registered body, reuse when identical); the referencing binding is
re-pinned; and the composed pack registers the refined body at the resolved version — so the activated HITL form
renders the operator's labels/dropdowns, not a raw JSON blob. Domain-neutral (dining fixture, reused verbatim).
"""
import pytest
from amendia_contracts.artifact_schema import ArtifactSchemaRegistration, ArtifactStatus

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CreateSessionRequest,
    DeclareArtifactRequest,
    RefineArtifactRequest,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedBindingIO,
    StagedTriageRule,
)
from app.services.onboarding import OnboardingService, TransitionError
from tests.conftest import load_sample
from tests.test_human_task_outputs import _DINEIN_BPMN, _ORDER_SCHEMA, _VALIDATE_TOOL

OWNER = "usr-owner"

# a refined schema: an enum + JSON-Schema `title` labels the plain declared schema lacks.
_REFINED = {
    "type": "object",
    "properties": {
        "order_type": {"type": "string", "title": "Order type", "enum": ["dine_in", "takeaway"]},
        "party_size": {"type": "integer", "title": "Party size"},
        "requested_items": {"type": "array", "title": "Requested items", "items": {"type": "string"}},
    },
    "required": ["order_type"],
}


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo, fake_introspector):
    return OnboardingService(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
                             fake_introspector, sample_envelopes=[load_sample()], profile="common_executable")


async def _seed(svc):
    s = await svc.create(CreateSessionRequest(pack_key="dinein-refine", version="1.0.0", title="t",
                                              default_domain="dining"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=_DINEIN_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_VALIDATE_TOOL]), owner=OWNER)
    s = await svc.declare_artifact(s.session_id, DeclareArtifactRequest(
        artifact_key="art.dining.order", title="Order", json_schema=_ORDER_SCHEMA), owner=OWNER)
    binds = [
        BindingInput(element_id="TakeOrder", element_kind="userTask", executor_type="human", role="role.server",
                     outputs=[StagedBindingIO(name="order", schema_ref="art.dining.order@^1.0.0")]),
        BindingInput(element_id="ValidateOrder", element_kind="serviceTask", executor_type="capability",
                     capability_ref="cap.dining.validate_order@^1.0.0", hitl_mode="none"),
    ]
    return await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=binds), owner=OWNER)


async def test_refine_bumps_version_repoints_binding_and_pins_the_labeled_schema(svc, schema_repo):
    # a prior activation registered art.dining.order@1.0.0 with the ORIGINAL body globally.
    await schema_repo.insert(ArtifactSchemaRegistration(
        pack_key="dinein-refine", pack_version="1.0.0",
        artifact_key="art.dining.order", version="1.0.0", title="Order",
        json_schema=_ORDER_SCHEMA, status=ArtifactStatus.ACTIVE))
    s = await _seed(svc)

    s = await svc.refine_artifact(s.session_id, RefineArtifactRequest(
        artifact_key="art.dining.order", json_schema=_REFINED, title="Order (refined)"), owner=OWNER)

    art = next(a for a in s.authored_artifacts if a.artifact_key == "art.dining.order")
    assert art.version == "1.1.0"                                        # changed body → bumped past the registered 1.0.0
    assert art.title == "Order (refined)"
    assert art.json_schema["properties"]["order_type"]["enum"] == ["dine_in", "takeaway"]
    assert art.json_schema["properties"]["order_type"]["title"] == "Order type"
    # the binding output is re-pinned to the bumped version
    take = next(b for b in s.bindings if b.element_id == "TakeOrder")
    assert take.outputs[0].schema_ref == "art.dining.order@^1.1.0"

    # …and the composed pack registers the refined body at 1.1.0 with the labels/enum intact (drives the HITL form)
    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1, when={"field": "reason_codes", "op": "intersects", "value": ["AC01"]})]),
        owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    assert [f for f in s.dry_run_report["findings"] if f["severity"] == "error"] == []
    _manifest, _descs, regs = svc._compose(s)
    order_reg = next(r for r in regs if r.artifact_key == "art.dining.order")
    assert order_reg.version == "1.1.0"
    assert order_reg.json_schema["properties"]["order_type"]["enum"] == ["dine_in", "takeaway"]
    assert "art.dining.order@^1.1.0" in {str(a) for a in _manifest.artifacts}


async def test_refine_to_an_identical_registered_body_does_not_churn(svc, schema_repo):
    await schema_repo.insert(ArtifactSchemaRegistration(
        pack_key="dinein-refine", pack_version="1.0.0",
        artifact_key="art.dining.order", version="1.0.0", title="Order",
        json_schema=_ORDER_SCHEMA, status=ArtifactStatus.ACTIVE))
    s = await _seed(svc)
    s = await svc.refine_artifact(s.session_id, RefineArtifactRequest(
        artifact_key="art.dining.order", json_schema=_ORDER_SCHEMA), owner=OWNER)   # identical → reuse
    art = next(a for a in s.authored_artifacts if a.artifact_key == "art.dining.order")
    assert art.version == "1.0.0"
    assert next(b for b in s.bindings if b.element_id == "TakeOrder").outputs[0].schema_ref == "art.dining.order@^1.0.0"


async def test_refine_rejects_a_key_that_is_not_a_human_authored_artifact(svc):
    s = await _seed(svc)
    with pytest.raises(TransitionError) as ei:
        await svc.refine_artifact(s.session_id, RefineArtifactRequest(
            artifact_key="art.dining.not_authored", json_schema=_ORDER_SCHEMA), owner=OWNER)
    assert ei.value.status_code == 422
