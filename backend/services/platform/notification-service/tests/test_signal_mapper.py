"""The signal mapper is the security boundary — it must project ONLY whitelisted
id/label fields and never copy payload data."""
from __future__ import annotations

from app.events.signal_mapper import event_type, to_signal


def _rk(service: str, event: str) -> str:
    return f"{service}.{event}.v1"


def test_event_type_parses_second_to_last_segment():
    assert event_type("agent_runtime.hitl_task_created.v1") == "hitl_task_created"
    assert event_type("ingestor.trigger_dispatched.v1") == "trigger_dispatched"
    assert event_type("too.short") is None


def test_hitl_created_signal_has_ids_only():
    payload = {
        "event_id": "e1", "occurred_at": "x", "schema_version": "1",
        "task_id": "hitl-1", "process_instance_id": "pi-1", "trigger_id": "EXC-1",
        "element_id": "Task_Assess", "role": "role.payments.ops_analyst",
    }
    sig = to_signal(payload, _rk("agent_runtime", "hitl_task_created"))
    assert sig == {
        "type": "hitl_task_created", "trigger_id": "EXC-1",
        "process_instance_id": "pi-1", "task_id": "hitl-1", "element_id": "Task_Assess",
        "role": "role.payments.ops_analyst",
    }


def test_decided_signal_never_leaks_sensitive_fields():
    payload = {
        "task_id": "hitl-1", "process_instance_id": "pi-1", "trigger_id": "EXC-1",
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
    payload = {"process_instance_id": "pi-1", "trigger_id": "EXC-1",
               "pack_key": "wire-repair-standard", "pack_version": "1.0.0", "outcome": "End_Resolved"}
    sig = to_signal(payload, _rk("agent_runtime", "process_completed"))
    assert sig["type"] == "process_completed"
    assert sig["outcome"] == "End_Resolved"
    assert "pack_key" not in sig and "pack_version" not in sig  # not whitelisted


def test_process_failed_omits_reason_detail():
    payload = {"process_instance_id": "pi-1", "trigger_id": "EXC-1",
               "reason": "route_failed", "detail": "no gateway route matched"}
    sig = to_signal(payload, _rk("agent_runtime", "process_failed"))
    assert sig["type"] == "process_failed"
    assert "reason" not in sig and "detail" not in sig


def test_cohort_sla_signal_carries_ids_labels_only():
    # ADR-064 P4 — the CohortSlaEvent carries timing/business data (due_at, at_risk_at, detected_at, deadlines);
    # the signal must relay ONLY the ids/labels the browser needs to invalidate query keys — never the timing.
    payload = {
        "event_id": "e1", "occurred_at": "x", "schema_version": "1",
        "cohort_instance_id": "coh-1", "sla_id": "edge:a->b", "state": "breached", "owner": "external",
        # timing/business content — MUST NOT leak (the browser re-fetches over role-guarded GLEA REST):
        "cohort_def_id": "ach_cohort", "correlation_value": "CASE-1", "ref": "a->b", "clock": "wall",
        "due_at": "2026-08-12T12:05:00+00:00", "at_risk_at": "2026-08-12T12:03:00+00:00",
        "detected_at": "2026-08-12T12:05:01+00:00", "trace": {"correlation_id": "CASE-1"},
    }
    sig = to_signal(payload, _rk("agent_runtime", "cohort_sla"))
    assert sig == {
        "type": "cohort_sla", "cohort_instance_id": "coh-1",
        "sla_id": "edge:a->b", "state": "breached", "owner": "external",
    }
    for leaked in ("due_at", "at_risk_at", "detected_at", "correlation_value", "cohort_def_id", "ref", "clock", "trace"):
        assert leaked not in sig


def test_unknown_event_is_ignored():
    assert to_signal({"trigger_id": "EXC-1"}, _rk("agent_runtime", "some_other_event")) is None
    assert to_signal({"trigger_id": "EXC-1"}, "malformed-key") is None
