# tests/test_cohort_contracts.py
"""ADR-063 Phase 1 — cohort contracts: manifest membership round-trip + the lifecycle event/routing key."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from amendia_contracts.governance_events import CohortLifecycleEvent, CohortLifecycleOp
from amendia_contracts.process_pack import CohortMembership, ProcessPackManifest

SEED_MANIFEST = Path(__file__).resolve().parent.parent / "seed" / "wire-repair-standard" / "manifest.json"


def _base_manifest() -> dict:
    return json.loads(SEED_MANIFEST.read_text())


def test_manifest_without_cohort_membership_is_unchanged():
    m = ProcessPackManifest.model_validate(_base_manifest())
    assert m.cohort_membership is None
    # round-trips without introducing the field (absent → omitted-or-null, still validates back)
    again = ProcessPackManifest.model_validate(m.to_doc())
    assert again.cohort_membership is None


def test_manifest_with_cohort_membership_validates_and_round_trips():
    raw = _base_manifest()
    raw["cohort_membership"] = {"cohort_def_id": "wire_transfer_cohort", "correlation_key": "exception_id"}
    m = ProcessPackManifest.model_validate(raw)
    assert m.cohort_membership == CohortMembership(
        cohort_def_id="wire_transfer_cohort", correlation_key="exception_id")
    # survives a full JSON round-trip (the persisted shape)
    again = ProcessPackManifest.model_validate(m.to_doc())
    assert again.cohort_membership.cohort_def_id == "wire_transfer_cohort"
    assert again.cohort_membership.correlation_key == "exception_id"


def test_cohort_lifecycle_event_serializes_with_valid_routing_key():
    ev = CohortLifecycleEvent(
        event_id="e1", occurred_at=datetime.now(timezone.utc),
        cohort_def_id="wire_transfer_cohort", cohort_instance_id="coh-abc123", correlation_value="1v23p",
        op=CohortLifecycleOp.MEMBER_JOINED, process_instance_id="pi-1", pack_key="wire-repair-standard",
    )
    assert ev.routing_key() == "agent_runtime.cohort_lifecycle.v1"
    doc = ev.to_doc()
    assert doc["op"] == "member_joined"
    assert doc["correlation_value"] == "1v23p"
    assert doc["schema_version"] == "pin.platform.cohort_lifecycle/1.0"


def test_cohort_lifecycle_ops_cover_the_full_state_vocabulary():
    assert {o.value for o in CohortLifecycleOp} == {
        "opened", "member_joined", "closing", "closed", "late_join"}


def test_cohort_lifecycle_event_carries_close_outcome_and_pack_version():
    # ADR-063 Phase 3A: first-class close_outcome (closing/closed) + member pack_version (member_joined).
    joined = CohortLifecycleEvent(
        event_id="e1", occurred_at=datetime.now(timezone.utc), cohort_def_id="wtc",
        cohort_instance_id="coh-1", correlation_value="1v23p", op=CohortLifecycleOp.MEMBER_JOINED,
        process_instance_id="pi-a", pack_key="wire-repair-standard", pack_version="1.0.0")
    assert joined.to_doc()["pack_version"] == "1.0.0"

    closed = CohortLifecycleEvent(
        event_id="e2", occurred_at=datetime.now(timezone.utc), cohort_def_id="wtc",
        cohort_instance_id="coh-1", correlation_value="1v23p", op=CohortLifecycleOp.CLOSED,
        close_outcome="process_ended")
    doc = closed.to_doc()
    assert doc["close_outcome"] == "process_ended"
    # additive/optional — omitting them still validates (Phase 1/2 back-compat)
    assert CohortLifecycleEvent.model_validate(
        {k: v for k, v in doc.items() if k not in ("close_outcome", "pack_version")}).close_outcome is None
