# tests/test_triage_validation.py
"""Batch-4 — schema-aware triage validation. A rule referencing a field that isn't on the trigger
(`reason_code` vs the real `reason_codes`) or a type-incompatible op (`eq` on an array) used to validate clean
and silently never triage ("No process"). Now it is an element-named error at authoring time. Domain-neutral:
validated against the trigger shape (the deployment sample envelopes), never a hardcoded field name.
"""
import pytest

from app.models.onboarding import (
    AttachBpmnRequest,
    BindingInput,
    CreateSessionRequest,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetTriageRequest,
    StagedTriageRule,
)
from app.services.onboarding import TransitionError
from app.validation.predicates import infer_field_types, validate_predicate
from tests.conftest import MCP_BPMN
from tests.test_onboarding import _screen_selection

OWNER = "usr-owner"

# a stand-in trigger shape (what infer_field_types derives from a sample envelope).
_FT = {"exception_type": "string", "reason_codes": "array", "payment.msg_type": "string",
       "payment.settlement_amount.value": "number"}


# --------------------------------------------------------------------------- #
# Pure — infer_field_types + validate_predicate
# --------------------------------------------------------------------------- #

def test_infer_field_types_walks_nested_and_types():
    ft = infer_field_types([{"exception_type": "x", "reason_codes": ["AC01"],
                             "payment": {"msg_type": "pacs.008", "settlement_amount": {"value": 10.5}}}])
    assert ft["exception_type"] == "string"
    assert ft["reason_codes"] == "array"
    assert ft["payment.msg_type"] == "string"
    assert ft["payment.settlement_amount.value"] == "number"
    assert ft["payment"] == "object"


def test_unknown_field_is_an_error_with_nearest_match_suggestion():
    out = validate_predicate({"field": "reason_code", "op": "eq", "value": "AC01"}, _FT)
    assert len(out) == 1 and out[0]["code"] == "triage_field_unknown"
    assert out[0]["suggestion"] == "reason_codes"          # edit-distance nearest
    assert "did you mean 'reason_codes'" in out[0]["message"]


def test_scalar_op_on_array_field_is_a_type_mismatch():
    out = validate_predicate({"field": "reason_codes", "op": "eq", "value": "AC01"}, _FT)
    assert len(out) == 1 and out[0]["code"] == "triage_op_type_mismatch"
    assert "intersects" in out[0]["message"]


def test_valid_reason_codes_intersects_passes():
    assert validate_predicate({"field": "reason_codes", "op": "intersects", "value": ["AC01"]}, _FT) == []
    # a valid nested tree with scalar + starts_with + array ops
    tree = {"all": [{"field": "exception_type", "op": "eq", "value": "unable_to_apply"},
                    {"field": "payment.msg_type", "op": "starts_with", "value": "pacs.008"},
                    {"field": "reason_codes", "op": "intersects", "value": ["AC01"]}]}
    assert validate_predicate(tree, _FT) == []


def test_no_schema_is_a_graceful_no_op():
    # with no trigger schema available, nothing is flagged (structural check still runs elsewhere).
    assert validate_predicate({"field": "reason_code", "op": "eq", "value": "AC01"}, {}) == []
    assert validate_predicate({"field": "anything", "op": "eq", "value": 1}, None) == []


def test_ordered_op_on_number_ok_but_starts_with_on_number_flags():
    assert validate_predicate({"field": "payment.settlement_amount.value", "op": "gt", "value": 1}, _FT) == []
    bad = validate_predicate({"field": "payment.settlement_amount.value", "op": "starts_with", "value": "1"}, _FT)
    assert bad and bad[0]["code"] == "triage_op_type_mismatch"


# --------------------------------------------------------------------------- #
# Integration — set_triage blocks the bug, accepts the fix (against the sample envelope)
# --------------------------------------------------------------------------- #

async def _walk_to_bindings(svc):
    s = await svc.create(CreateSessionRequest(pack_key="triage-x", version="1.0.0", title="t",
                                              default_domain="payment"), owner=OWNER)
    s = await svc.attach_bpmn(s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    s = await svc.set_capabilities(s.session_id, SetCapabilitiesRequest(tools=[_screen_selection()]), owner=OWNER)
    s = await svc.set_bindings(s.session_id, SetBindingsRequest(bindings=[BindingInput(
        element_id="Task_Screen", element_kind="serviceTask", executor_type="capability",
        capability_ref="cap.payment.screen_party@^1.0.0", hitl_mode="review_after",
        hitl_role="role.payments.ops_analyst",
        input_sources={"screen_party_input": {"from": "trigger"}})]), owner=OWNER)
    return s


async def test_set_triage_blocks_unknown_field_with_suggestion(onboarding_service):
    s = await _walk_to_bindings(onboarding_service)
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_triage(s.session_id, SetTriageRequest(triage_rules=[
            StagedTriageRule(rule_id="r", priority=1,
                             when={"field": "reason_code", "op": "eq", "value": "AC01"})]), owner=OWNER)
    assert ei.value.status_code == 422
    err = next(e for e in ei.value.detail["errors"] if e.get("code") == "triage_field_unknown")
    assert err["field"] == "reason_code" and err["suggestion"] == "reason_codes"


async def test_set_triage_blocks_op_type_mismatch(onboarding_service):
    s = await _walk_to_bindings(onboarding_service)
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.set_triage(s.session_id, SetTriageRequest(triage_rules=[
            StagedTriageRule(rule_id="r", priority=1,
                             when={"field": "reason_codes", "op": "eq", "value": "AC01"})]), owner=OWNER)
    assert any(e.get("code") == "triage_op_type_mismatch" for e in ei.value.detail["errors"])


async def test_set_triage_accepts_the_correct_reason_codes_intersects(onboarding_service):
    s = await _walk_to_bindings(onboarding_service)
    s = await onboarding_service.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r", priority=1,
                         when={"field": "reason_codes", "op": "intersects", "value": ["AC01"]})]), owner=OWNER)
    assert s.triage_rules[0].when["op"] == "intersects"
    # the session also carries the trigger field map for the wizard's schema-aware Triage step
    assert s.trigger_fields.get("reason_codes") == "array"
