# tests/test_mapper.py
"""The event→audit_events projection is correct AND domain-neutral (ADR-058 review gate)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import orjson
import pytest

from app.clickhouse import schema
from app.events.mapper import UnmappableEvent, event_kind, to_row, waiver_rows


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


def test_pack_waiver_fans_out_one_row_per_waiver():
    # ADR-065 P4b: a publish PackLifecycleEvent fans out to one `pack_waiver` row per waiver — same structural
    # columns, author in `actor`, publisher + capability + justification on the row's payload.
    payload = _envelope(
        pack_key="wire-repair-standard", version="1.2.0", op="publish", actor="usr-publisher",
        trace={"correlation_id": "", "trace_id": ""},
        waivers=[
            {"element_id": "Task_NotifyAssessed", "capability_id": "cap.payment.notify_parties",
             "justification": "Idempotent handback; the orchestrator re-confirms receipt.",
             "waived_by": "usr-author", "waived_at": "2026-09-01T00:00:00+00:00"},
            {"element_id": "Task_Record", "capability_id": "cap.payment.record",
             "justification": "Write-once ledger append; a re-run is a no-op.",
             "waived_by": "usr-author2", "waived_at": "2026-09-01T00:01:00+00:00"},
        ],
    )
    rows = waiver_rows("process_registry.pack_lifecycle.v1", payload)
    assert len(rows) == 2
    for r in rows:
        assert set(r.keys()) == set(schema.INSERT_COLUMNS)          # SAME domain-neutral columns as any audit row
        assert r["kind"] == "pack_waiver"
        assert r["pack_key"] == "wire-repair-standard" and r["pack_version"] == "1.2.0"
    r0 = rows[0]
    assert r0["element_id"] == "Task_NotifyAssessed"
    assert r0["actor"] == "usr-author"                             # the author is the actor column ("who allowed it")
    assert r0["event_id"].endswith(":waiver:Task_NotifyAssessed")  # deterministic → idempotent redelivery
    p = orjson.loads(r0["payload"])
    assert p["capability_id"] == "cap.payment.notify_parties"
    assert p["publisher"] == "usr-publisher"                       # publisher is a DIFFERENT fact from waived_by
    assert p["justification"].startswith("Idempotent")


def test_pack_waiver_no_fanout_when_absent_or_not_publish():
    # deprecate / rollback (or publish with no waivers) → no fan-out; a non-pack event → no rows.
    assert waiver_rows("process_registry.pack_lifecycle.v1",
                       _envelope(op="deprecate", pack_key="p", version="1.0.0")) == []
    assert waiver_rows("agent_runtime.hitl_task_decided.v1",
                       _envelope(waivers=[{"element_id": "X"}])) == []


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
