# tests/test_mapper.py
"""The event→audit_events projection is correct AND domain-neutral (ADR-058 review gate)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import orjson
import pytest

from app.clickhouse import schema
from app.events.mapper import UnmappableEvent, event_kind, to_row


def _envelope(**extra):
    base = {
        "event_id": uuid.uuid4().hex,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(extra)
    return base


def test_row_columns_are_exactly_the_structural_schema():
    payload = _envelope(
        trigger_id="EXC-1", element_id="Task_X", role="role.ops.analyst",
        decision="approve", decided_by="u1", sod_satisfied=True,
        trace={"correlation_id": "EXC-1", "trace_id": "a" * 32},
    )
    row = to_row("agent_runtime.hitl_task_decided.v1", payload)
    # Domain-neutrality gate: the row's columns are EXACTLY the structural schema — no ad-hoc/business key.
    assert set(row.keys()) == set(schema.INSERT_COLUMNS)
    assert row["kind"] == "hitl_task_decided"
    assert row["correlation_id"] == "EXC-1"
    assert row["trace_id"] == "a" * 32
    assert row["decision"] == "approve"
    assert row["decided_by"] == "u1"
    assert row["actor"] == "u1"          # decided_by is the acting human
    assert row["sod_satisfied"] == 1     # Nullable(UInt8)


def test_egress_decision_maps_to_egress_columns_not_decision():
    payload = _envelope(
        process_instance_id="pi-1", element_id="Task_Y", capability_id="cap.z",
        execution_mode="native", host="evil.example", decision="deny", enforced=True,
        trace={"correlation_id": "EXC-2", "trace_id": "b" * 32},
    )
    row = to_row("agent_runtime.egress_decision.v1", payload)
    assert row["egress_decision"] == "deny"
    assert row["egress_host"] == "evil.example"
    assert row["decision"] == ""         # egress does NOT populate the generic decision column


def test_pack_lifecycle_version_aliases_pack_version():
    payload = _envelope(pack_key="wire-repair-standard", version="1.2.0", op="publish", actor="owner1",
                        trace={"correlation_id": "reg-1", "trace_id": ""})
    row = to_row("process_registry.pack_lifecycle.v1", payload)
    assert row["pack_key"] == "wire-repair-standard"
    assert row["pack_version"] == "1.2.0"
    assert row["correlation_id"] == "reg-1"


def test_artifact_committed_populates_artifact_key():
    payload = _envelope(
        artifact_key="art.payment.resolution_record", schema_ref="art.payment.resolution_record@1.0.0",
        element_id="Task_Record", actor="cap.x", actor_kind="capability", authored_by_human=False,
        trace={"correlation_id": "EXC-9", "trace_id": "c" * 32},
    )
    row = to_row("agent_runtime.artifact_committed.v1", payload)
    assert row["artifact_key"] == "art.payment.resolution_record"     # the decision-trail/lineage join key
    assert row["schema_ref"] == "art.payment.resolution_record@1.0.0"


def test_non_artifact_kinds_leave_artifact_key_empty():
    payload = _envelope(trigger_id="EXC-1", trace={"correlation_id": "EXC-1"})
    assert to_row("agent_runtime.process_completed.v1", payload)["artifact_key"] == ""


def test_payload_column_preserves_the_full_event():
    payload = _envelope(trigger_id="EXC-3", trace={"correlation_id": "EXC-3"})
    row = to_row("agent_runtime.process_completed.v1", payload)
    assert orjson.loads(row["payload"])["event_id"] == payload["event_id"]


def test_missing_event_id_is_unmappable():
    with pytest.raises(UnmappableEvent):
        to_row("agent_runtime.process_completed.v1", {"occurred_at": datetime.now(timezone.utc).isoformat()})


def test_event_kind_extracts_middle_segment():
    assert event_kind("identity.role_changed.v1") == "role_changed"
    assert event_kind("weird") == "weird"
