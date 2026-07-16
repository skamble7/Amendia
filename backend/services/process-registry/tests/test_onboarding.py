"""OnboardingSession state machine + MCP inference + safety guards + e2e commit.

The whole flow runs against an in-memory MCP introspector (no live network) and the
mongomock repos. The end-to-end test proves an operator can go basics → BPMN → MCP tools
→ bindings → triage → policies → assemble → commit, and that the committed pack ends
``active`` with pinned resolution — and that a re-run of commit is a no-op.
"""
import pytest

from amendia_contracts.capability import CapabilityDescriptor
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
    StagedGatewayVariable,
    StagedTriageRule,
)
from app.services.mcp_introspect import (
    RawMcpTool,
    evaluate_compliance,
    infer_capability,
    normalize_artifact_schema,
)
from app.services.onboarding import TransitionError
from tests.conftest import MCP_BPMN

OWNER = "usr-owner"

_SCREEN_IN = {"type": "object", "properties": {"party": {"type": "string"}}, "required": ["party"]}
_SCREEN_OUT = {"type": "object", "properties": {"hit": {"type": "boolean"}}, "required": ["hit"]}


def _screen_selection(*, side_effect="read_only", min_hitl_mode=None):
    return CapabilityToolSelection(
        tool="screen_party", endpoint="http://mcp.local/mcp", transport="streamable_http",
        input_schema=_SCREEN_IN, output_schema=_SCREEN_OUT,
        side_effect=side_effect, idempotent=True, min_hitl_mode=min_hitl_mode,
    )


async def _walk_to_capabilities(svc, *, side_effect="read_only", min_hitl_mode=None):
    s = await svc.create(CreateSessionRequest(pack_key="mcp-screen", version="1.0.0", title="MCP screen"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    s = await svc.set_capabilities(
        s.session_id,
        SetCapabilitiesRequest(tools=[_screen_selection(side_effect=side_effect, min_hitl_mode=min_hitl_mode)]),
        owner=OWNER,
    )
    return s


def _binding(*, hitl_mode="review_after", role="role.payments.ops_analyst"):
    return BindingInput(
        element_id="Task_Screen", element_kind="serviceTask", executor_type="capability",
        capability_ref="cap.payment.screen_party@^1.0.0", hitl_mode=hitl_mode, hitl_role=role,
    )


async def _walk_to_assembled(svc):
    s = await _walk_to_capabilities(svc)
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=[_binding()]), owner=OWNER)
    s = await svc.set_triage(
        s.session_id,
        SetTriageRequest(triage_rules=[StagedTriageRule(rule_id="r1", priority=100,
                                                        when={"field": "reason_code", "op": "eq", "value": "AC01"})]),
        owner=OWNER,
    )
    s = await svc.set_policies(
        s.session_id,
        SetPoliciesRequest(gateway_variables=[], sod_policies=[], roles=["role.payments.ops_analyst"]),
        owner=OWNER,
    )
    s = await svc.assemble(s.session_id, owner=OWNER)
    return s


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #

def test_normalize_forces_id_type_and_additional_properties():
    schema, warnings = normalize_artifact_schema(
        {"type": "object", "properties": {"a": {"type": "string"}}},
        artifact_key="art.payment.screen_party_input", version="1.0.0",
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["$id"] == "https://amendia.dev/schemas/artifacts/payment/screen_party_input/1.0.0.json"
    assert schema["additionalProperties"] is False
    assert any("additionalProperties" in w for w in warnings)


def test_normalize_rejects_external_ref():
    with pytest.raises(ValueError):
        normalize_artifact_schema(
            {"type": "object", "properties": {"x": {"$ref": "https://evil.example/x.json"}}},
            artifact_key="art.payment.thing_input", version="1.0.0",
        )


def test_compliance_missing_output_schema_is_non_compliant():
    verdict = evaluate_compliance(RawMcpTool("t", None, _SCREEN_IN, None))
    assert verdict.compliant is False
    assert any("outputSchema" in r for r in verdict.reasons)


def test_compliance_non_object_root_is_non_compliant():
    verdict = evaluate_compliance(RawMcpTool("t", None, {"type": "array"}, _SCREEN_OUT))
    assert verdict.compliant is False


def test_infer_capability_non_compliant_raises():
    with pytest.raises(ValueError):
        infer_capability(
            tool="notify", endpoint="http://x", transport="streamable_http", headers={}, domain="payment",
            input_schema=_SCREEN_IN, output_schema=None,
            input_artifact_key="art.payment.notify_input", output_artifact_key="art.payment.notify_output",
            capability_id="cap.payment.notify", artifact_version="1.0.0", capability_version="1.0.0",
            side_effect="read_only", idempotent=None, min_hitl_mode=None, title=None, description=None,
        )


# --------------------------------------------------------------------------- #
# State machine + guards
# --------------------------------------------------------------------------- #

async def test_create_rejects_existing_active_pack(onboarding_service, onboarded):
    # `onboarded` activates the seed pack (wire-repair-standard@…).
    from tests.conftest import load_manifest
    m = load_manifest()
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.create(
            CreateSessionRequest(pack_key=m.pack_key, version=m.version, title="dup"), owner=OWNER
        )
    assert ei.value.status_code == 409


async def test_attach_bpmn_builds_inventory(onboarding_service):
    s = await onboarding_service.create(CreateSessionRequest(pack_key="mcp-screen", version="1.0.0", title="t"), owner=OWNER)
    s = await onboarding_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    assert s.state == OnboardingState.BPMN_ATTACHED
    assert s.bpmn.process_id == "mcp_test_process"
    assert s.bpmn.service_tasks == ["Task_Screen"]


async def test_introspect_flags_compliance(onboarding_service):
    from app.models.onboarding import IntrospectMcpRequest
    resp = await onboarding_service.introspect_mcp(IntrospectMcpRequest(endpoint="http://mcp.local/mcp"))
    by_name = {t.name: t for t in resp.tools}
    assert by_name["screen_party"].compliance.compliant is True
    assert by_name["screen_party"].suggested_capability_id == "cap.payment.screen_party"
    assert by_name["notify_ops"].compliance.compliant is False


async def test_set_capabilities_rejects_non_compliant_tool(onboarding_service):
    s = await onboarding_service.create(CreateSessionRequest(pack_key="mcp-x", version="1.0.0", title="t"), owner=OWNER)
    s = await onboarding_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    bad = CapabilityToolSelection(tool="notify_ops", endpoint="http://x", input_schema={"type": "object"}, output_schema=None)
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[bad]), owner=OWNER)
    assert ei.value.status_code == 422


async def test_bindings_bijection_missing_binding(onboarding_service):
    s = await _walk_to_capabilities(onboarding_service)
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_bindings(s.session_id, SetBindingsRequest(bindings=[]), owner=OWNER)
    assert ei.value.status_code == 422
    msgs = str(ei.value.detail)
    assert "Task_Screen" in msgs and "no binding" in msgs


async def test_bindings_orphan_binding(onboarding_service):
    s = await _walk_to_capabilities(onboarding_service)
    orphan = BindingInput(element_id="Task_Ghost", element_kind="serviceTask", executor_type="capability",
                          capability_ref="cap.payment.screen_party@^1.0.0", hitl_mode="review_after",
                          hitl_role="role.payments.ops_analyst")
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_bindings(s.session_id, SetBindingsRequest(bindings=[orphan]), owner=OWNER)
    assert ei.value.status_code == 422


async def test_side_effect_requires_approve_actions(onboarding_service):
    s = await _walk_to_capabilities(onboarding_service, side_effect="side_effectful")
    # review_after is too weak for a side-effectful capability.
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_bindings(
            s.session_id, SetBindingsRequest(bindings=[_binding(hitl_mode="review_after")]), owner=OWNER
        )
    assert ei.value.status_code == 422
    assert any(e.get("allowed_min_mode") == "approve_actions" for e in ei.value.detail["errors"])
    # approve_actions passes.
    s = await onboarding_service.set_bindings(
        s.session_id, SetBindingsRequest(bindings=[_binding(hitl_mode="approve_actions")]), owner=OWNER
    )
    assert s.state == OnboardingState.BINDINGS_SET


async def test_hitl_role_required(onboarding_service):
    s = await _walk_to_capabilities(onboarding_service)
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_bindings(
            s.session_id, SetBindingsRequest(bindings=[_binding(hitl_mode="review_after", role=None)]), owner=OWNER
        )
    assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
# Invalidation cascade
# --------------------------------------------------------------------------- #

async def test_editing_capabilities_clears_bindings(onboarding_service):
    s = await _walk_to_capabilities(onboarding_service)
    s = await onboarding_service.set_bindings(s.session_id, SetBindingsRequest(bindings=[_binding()]), owner=OWNER)
    assert s.bindings
    s = await onboarding_service.set_capabilities(
        s.session_id, SetCapabilitiesRequest(tools=[_screen_selection()]), owner=OWNER
    )
    assert s.bindings == []
    assert "bindings" in s.last_cleared
    assert s.state == OnboardingState.CAPABILITIES_RESOLVED


async def test_reattach_bpmn_clears_bindings_and_gateway_vars(onboarding_service):
    s = await _walk_to_capabilities(onboarding_service)
    s = await onboarding_service.set_bindings(s.session_id, SetBindingsRequest(bindings=[_binding()]), owner=OWNER)
    s = await onboarding_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    assert s.bindings == []
    assert "bindings" in s.last_cleared
    # capabilities survive → back at capabilities_resolved, not bpmn_attached.
    assert s.state == OnboardingState.CAPABILITIES_RESOLVED


async def test_reject_parallel_gateway_bpmn(onboarding_service):
    s = await onboarding_service.create(CreateSessionRequest(pack_key="p-x", version="1.0.0", title="t"), owner=OWNER)
    parallel = MCP_BPMN.replace(
        '<bpmn:serviceTask id="Task_Screen" name="Screen party"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>',
        '<bpmn:parallelGateway id="Gw_P"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:parallelGateway>',
    )
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=parallel), owner=OWNER)
    assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
# Assemble + end-to-end commit (idempotent)
# --------------------------------------------------------------------------- #

async def test_assemble_dry_run_clean(onboarding_service):
    s = await _walk_to_assembled(onboarding_service)
    assert s.state == OnboardingState.ASSEMBLED
    assert s.dry_run_report is not None
    errors = [f for f in s.dry_run_report["findings"] if f["severity"] == "error"]
    assert errors == [], errors


async def test_commit_activates_pack_and_is_idempotent(onboarding_service, cap_repo, schema_repo, pack_repo):
    s = await _walk_to_assembled(onboarding_service)
    s = await onboarding_service.commit(s.session_id, owner=OWNER)
    assert s.state == OnboardingState.COMPLETED
    assert s.result_pack == "mcp-screen@1.0.0"
    assert all(step.status == "done" for step in s.commit_progress)

    # pack is active with pinned resolution
    pack = await pack_repo.get("mcp-screen", "1.0.0")
    assert pack.status.value == "active"
    resolution = await pack_repo.get_resolution("mcp-screen", "1.0.0")
    assert resolution["capabilities"]["cap.payment.screen_party"] == "1.0.0"

    # staged artifacts + capability actually registered
    assert await cap_repo.get("cap.payment.screen_party", "1.0.0") is not None
    assert await schema_repo.get("art.payment.screen_party_input", "1.0.0") is not None

    # re-run commit → no-op, pack stays active
    s2 = await onboarding_service.commit(s.session_id, owner=OWNER)
    assert s2.state == OnboardingState.COMPLETED
    pack2 = await pack_repo.get("mcp-screen", "1.0.0")
    assert pack2.status.value == "active"


async def test_completed_session_is_immutable(onboarding_service):
    s = await _walk_to_assembled(onboarding_service)
    await onboarding_service.commit(s.session_id, owner=OWNER)
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    assert ei.value.status_code == 409


# --------------------------------------------------------------------------- #
# HTTP wiring + owner gating
# --------------------------------------------------------------------------- #

async def test_http_create_and_list_and_get(client):
    r = await client.post("/onboarding", json={"pack_key": "http-pack", "version": "1.0.0", "title": "HTTP"})
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    assert r.json()["state"] == "initiated"

    lst = await client.get("/onboarding")
    assert lst.status_code == 200 and any(s["session_id"] == sid for s in lst.json())

    got = await client.get(f"/onboarding/{sid}")
    assert got.status_code == 200 and got.json()["basics"]["pack_key"] == "http-pack"

    assert (await client.delete(f"/onboarding/{sid}")).status_code == 204
    assert (await client.get(f"/onboarding/{sid}")).status_code == 404


async def test_http_introspect_mcp(client):
    r = await client.post("/capabilities/introspect-mcp", json={"endpoint": "http://mcp.local/mcp", "domain": "payment"})
    assert r.status_code == 200, r.text
    names = {t["name"]: t["compliance"]["compliant"] for t in r.json()["tools"]}
    assert names == {"screen_party": True, "notify_ops": False}
