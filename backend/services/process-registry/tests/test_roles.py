"""Roles-in-use catalog: derived-from-bindings ids + per-pack metadata sidecar.

Two paths: (a) the seed pack is onboarded via the real pipeline (no authored metadata)
→ its role ids surface with sources and humanized labels; (b) a pack driven through the
onboarding wizard *with* ``role_meta`` → after commit the authored label/description win.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CreateSessionRequest,
    RoleMeta,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
    StagedTriageRule,
)
from app.services.onboarding import humanize_role
from app.services.roles import list_roles_in_use
from tests.conftest import MCP_BPMN
from tests.test_onboarding import _screen_selection

OWNER = "usr-owner"


# --------------------------------------------------------------------------- #
# humanize helper
# --------------------------------------------------------------------------- #

def test_humanize_role():
    assert humanize_role("role.payments.ops_analyst") == "Ops Analyst"
    assert humanize_role("role.lending.underwriter") == "Underwriter"


# --------------------------------------------------------------------------- #
# Derived ids (seed pack, no authored metadata)
# --------------------------------------------------------------------------- #

async def test_seed_roles_derived_from_bindings(pack_repo, onboarded):
    roles = await list_roles_in_use(pack_repo)
    by_id = {r.role_id: r for r in roles}
    assert "role.payments.ops_analyst" in by_id
    assert "role.payments.ops_approver" in by_id
    analyst = by_id["role.payments.ops_analyst"]
    # No onboarding sidecar for the seed → derived-only: label/description are null.
    assert analyst.label is None
    assert analyst.description is None
    assert "wire-repair-standard@1.0.0" in analyst.sources


async def test_http_roles_endpoint(client, onboarded):
    r = await client.get("/roles")
    assert r.status_code == 200, r.text
    ids = {row["role_id"] for row in r.json()}
    assert {"role.payments.ops_analyst", "role.payments.ops_approver"} <= ids


# --------------------------------------------------------------------------- #
# Authored metadata (onboarding wizard → commit → sidecar)
# --------------------------------------------------------------------------- #

async def _walk_and_commit_with_meta(svc, role_meta):
    s = await svc.create(CreateSessionRequest(pack_key="mcp-screen", version="1.0.0", title="MCP screen", default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_screen_selection()]), owner=OWNER)
    binding = BindingInput(
        element_id="Task_Screen", element_kind="serviceTask", executor_type="capability",
        capability_ref="cap.payment.screen_party@^1.0.0", hitl_mode="review_after",
        hitl_role="role.payments.ops_analyst",
        input_sources={"screen_party_input": {"from": "trigger"}},
    )
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=[binding]), owner=OWNER)
    s = await svc.set_triage(
        s.session_id,
        SetTriageRequest(triage_rules=[StagedTriageRule(rule_id="r1", priority=100,
                                                        when={"field": "reason_code", "op": "eq", "value": "AC01"})]),
        owner=OWNER,
    )
    s = await svc.set_policies(
        s.session_id,
        SetPoliciesRequest(roles=["role.payments.ops_analyst"], role_meta=role_meta),
        owner=OWNER,
    )
    s = await svc.assemble(s.session_id, owner=OWNER)
    return await svc.commit(s.session_id, owner=OWNER)


async def test_authored_role_meta_surfaces_after_commit(onboarding_service, pack_repo):
    meta = {"role.payments.ops_analyst": RoleMeta(label="Sanctions Analyst", description="Reviews screening hits")}
    s = await _walk_and_commit_with_meta(onboarding_service, meta)
    assert s.result_pack == "mcp-screen@1.0.0"

    saved = await pack_repo.get_pack_roles("mcp-screen", "1.0.0")
    by_id = {r["role_id"]: r for r in saved}
    assert by_id["role.payments.ops_analyst"]["label"] == "Sanctions Analyst"
    assert by_id["role.payments.ops_analyst"]["description"] == "Reviews screening hits"

    roles = await list_roles_in_use(pack_repo)
    analyst = next(r for r in roles if r.role_id == "role.payments.ops_analyst")
    assert analyst.label == "Sanctions Analyst"
    assert analyst.description == "Reviews screening hits"
    assert "mcp-screen@1.0.0" in analyst.sources


async def test_missing_meta_falls_back_to_humanized_label(onboarding_service, pack_repo):
    s = await _walk_and_commit_with_meta(onboarding_service, {})
    saved = await pack_repo.get_pack_roles("mcp-screen", "1.0.0")
    by_id = {r["role_id"]: r for r in saved}
    # No authored metadata → humanized label, empty description.
    assert by_id["role.payments.ops_analyst"]["label"] == "Ops Analyst"
    assert by_id["role.payments.ops_analyst"]["description"] == ""


async def test_set_policies_drops_meta_for_unknown_roles(onboarding_service):
    s = await onboarding_service.create(
        CreateSessionRequest(pack_key="mcp-screen", version="1.0.0", title="t", default_domain="payment"), owner=OWNER)
    s = await onboarding_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    s = await onboarding_service.set_capabilities(
        s.session_id, SetCapabilitiesRequest(tools=[_screen_selection()]), owner=OWNER)
    binding = BindingInput(
        element_id="Task_Screen", element_kind="serviceTask", executor_type="capability",
        capability_ref="cap.payment.screen_party@^1.0.0", hitl_mode="review_after",
        hitl_role="role.payments.ops_analyst",
        input_sources={"screen_party_input": {"from": "trigger"}},
    )
    s = await onboarding_service.set_bindings(s.session_id, SetBindingsRequest(bindings=[binding]), owner=OWNER)
    s = await onboarding_service.set_triage(
        s.session_id,
        SetTriageRequest(triage_rules=[StagedTriageRule(rule_id="r1", priority=100,
                                                        when={"field": "reason_code", "op": "eq", "value": "AC01"})]),
        owner=OWNER,
    )
    s = await onboarding_service.set_policies(
        s.session_id,
        SetPoliciesRequest(
            roles=["role.payments.ops_analyst"],
            role_meta={
                "role.payments.ops_analyst": RoleMeta(label="Analyst"),
                "role.payments.ghost": RoleMeta(label="Ghost"),  # not referenced → dropped
            },
        ),
        owner=OWNER,
    )
    assert set(s.role_meta) == {"role.payments.ops_analyst"}
