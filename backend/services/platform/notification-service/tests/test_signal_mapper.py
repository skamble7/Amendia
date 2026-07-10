"""The signal mapper is the security boundary — it must project ONLY whitelisted
id/label fields and never copy payload data."""
from __future__ import annotations

from app.events.signal_mapper import event_type, to_signal


def _rk(service: str, event: str, tenant: str = "bank-alpha") -> str:
    return f"{tenant}.{service}.{event}.v1"


def test_event_type_parses_second_to_last_segment():
    assert event_type("bank-alpha.agent_runtime.hitl_task_created.v1") == "hitl_task_created"
    assert event_type("t.ingestor.exception_dispatched.v1") == "exception_dispatched"
    assert event_type("too.short") is None


def test_hitl_created_signal_has_ids_only():
    payload = {
        "event_id": "e1", "tenant": "bank-alpha", "occurred_at": "x", "schema_version": "1",
        "task_id": "hitl-1", "process_instance_id": "pi-1", "exception_id": "EXC-1",
        "element_id": "Task_Assess", "role": "role.payments.ops_analyst",
    }
    sig = to_signal(payload, _rk("agent_runtime", "hitl_task_created"))
    assert sig == {
        "type": "hitl_task_created", "tenant": "bank-alpha", "exception_id": "EXC-1",
        "process_instance_id": "pi-1", "task_id": "hitl-1", "element_id": "Task_Assess",
        "role": "role.payments.ops_analyst",
    }


def test_decided_signal_never_leaks_sensitive_fields():
    payload = {
        "tenant": "t", "task_id": "hitl-1", "process_instance_id": "pi-1", "exception_id": "EXC-1",
        "element_id": "Task_Assess", "role": "role.payments.ops_approver",
        # sensitive — must NOT appear in the signal:
        "decision": "approve", "decided_by": "usr-123", "comment": "secret rationale",
        "edits": {"creditor": "IT60..."}, "trace": {"correlation_id": "EXC-1"},
    }
    sig = to_signal(payload, _rk("agent_runtime", "hitl_task_decided"))
    assert sig["type"] == "hitl_task_decided"
    for leaked in ("decision", "decided_by", "comment", "edits", "trace"):
        assert leaked not in sig


def test_process_completed_carries_outcome():
    payload = {"tenant": "t", "process_instance_id": "pi-1", "exception_id": "EXC-1",
               "pack_key": "wire-repair-standard", "pack_version": "1.0.0", "outcome": "End_Resolved"}
    sig = to_signal(payload, _rk("agent_runtime", "process_completed"))
    assert sig["type"] == "process_completed"
    assert sig["outcome"] == "End_Resolved"
    assert "pack_key" not in sig and "pack_version" not in sig  # not whitelisted


def test_process_failed_omits_reason_detail():
    payload = {"tenant": "t", "process_instance_id": "pi-1", "exception_id": "EXC-1",
               "reason": "route_failed", "detail": "no gateway route matched"}
    sig = to_signal(payload, _rk("agent_runtime", "process_failed"))
    assert sig["type"] == "process_failed"
    assert "reason" not in sig and "detail" not in sig


def test_unknown_event_is_ignored():
    assert to_signal({"tenant": "t"}, _rk("agent_runtime", "some_other_event")) is None
    assert to_signal({"tenant": "t"}, "malformed-key") is None
