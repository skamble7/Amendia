# tests/test_models_invariants.py
import pytest
from pydantic import ValidationError

from app.models.dispatch import DispatchAcceptedEvent, DispatchRejectedEvent
from app.models.hitl_task import HitlTask
from app.models.process_pack import (
    AllPredicate,
    Hitl,
    LeafPredicate,
    NotPredicate,
    TriageRule,
)
from app.models.capability import CapabilityDescriptor


def test_hitl_role_required_unless_none():
    Hitl.model_validate({"mode": "none"})  # ok, no role
    Hitl.model_validate({"mode": "review_after", "role": "role.payments.ops_analyst"})
    with pytest.raises(ValidationError):
        Hitl.model_validate({"mode": "review_after"})  # missing role


def test_recursive_predicate_parsing():
    rule = TriageRule.model_validate({
        "rule_id": "wire-uta-repairable-codes",
        "priority": 100,
        "when": {"all": [
            {"field": "exception_type", "op": "eq", "value": "unable_to_apply"},
            {"field": "payment.msg_type", "op": "starts_with", "value": "pacs.008"},
            {"field": "reason_codes", "op": "intersects", "value": ["AC01", "AC04", "RC01", "BE04"]},
            {"not": {"field": "foo", "op": "exists"}},
        ]},
    })
    assert isinstance(rule.when, AllPredicate)
    assert isinstance(rule.when.all[0], LeafPredicate)
    assert isinstance(rule.when.all[3], NotPredicate)
    assert isinstance(rule.when.all[3].not_, LeafPredicate)
    # `not` alias round-trips
    assert rule.model_dump(by_alias=True)["when"]["all"][3] == {
        "not": {"field": "foo", "op": "exists", "value": None}
    }


def _valid_task(**overrides):
    base = {
        "task_id": "T-1", "process_instance_id": "PI-1",
        "pack_key": "wire-repair-standard", "pack_version": "1.0.0",
        "element_id": "Task_ApproveRepair", "exception_id": "EXC-1",
        "hitl_mode": "manual", "role": "role.payments.ops_approver",
        "title": "Approve", "payload": {}, "allowed_decisions": ["complete", "escalate"],
        "status": "open", "created_at": "2026-07-07T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_decided_task_requires_decision():
    with pytest.raises(ValidationError):
        HitlTask.model_validate(_valid_task(status="decided"))


def test_decision_must_be_allowed():
    with pytest.raises(ValidationError):
        HitlTask.model_validate(_valid_task(
            status="decided",
            decision={"decision": "approve", "decided_by": "u1", "decided_at": "2026-07-07T00:00:00Z"},
        ))
    # complete is allowed → ok
    HitlTask.model_validate(_valid_task(
        status="decided",
        decision={"decision": "complete", "decided_by": "u1", "decided_at": "2026-07-07T00:00:00Z"},
    ))


def test_dispatch_rejected_requires_reason():
    with pytest.raises(ValidationError):
        DispatchRejectedEvent.model_validate({
            "event_id": "e1", "occurred_at": "2026-07-07T00:00:00Z",
            "exception_id": "EXC-1", "detail": "x", "trace": {"correlation_id": "EXC-1"},
        })


def test_capability_runtime_kind_must_match():
    with pytest.raises(ValidationError):
        CapabilityDescriptor.model_validate({
            "descriptor_version": "1.0", "capability_id": "cap.payment.x", "version": "1.0.0",
            "title": "X", "kind": "skill", "side_effect": "read_only",
            "inputs": [], "outputs": [],
            "runtime": {"kind": "mcp", "endpoint": "http://x", "tools": ["t"]},
            "status": "active",
        })


def test_event_routing_key_delegates_to_rk():
    ev = DispatchAcceptedEvent.model_validate({
        "event_id": "e1", "occurred_at": "2026-07-07T00:00:00Z",
        "exception_id": "EXC-1", "process_instance_id": "PI-1",
        "pack_key": "wire-repair-standard", "pack_version": "1.0.0",
        "trace": {"correlation_id": "EXC-1"},
    })
    assert ev.routing_key() == "agent_runtime.dispatch_accepted.v1"
