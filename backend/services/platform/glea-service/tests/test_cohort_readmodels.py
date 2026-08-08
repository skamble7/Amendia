# tests/test_cohort_readmodels.py
"""ADR-063 Phase 3A — cohort read-model assembly (pure, no ClickHouse)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.readmodels import build_cohort_detail, build_cohort_list

T0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _cev(op, *, at, cohort="coh-1", defid="wire_transfer_cohort", value="1v23p",
         pid="", pack="", ver="", mcid="", outcome="", detail=""):
    return {
        "event_id": f"{op}-{pid}-{at.isoformat()}", "occurred_at": at, "op": op,
        "cohort_instance_id": cohort, "cohort_def_id": defid, "correlation_value": value,
        "member_process_instance_id": pid, "member_pack_key": pack, "member_pack_version": ver,
        "member_correlation_id": mcid, "close_outcome": outcome, "detail": detail, "trace_id": "",
    }


def _audit(cid, kind, at, outcome=""):
    return {"correlation_id": cid, "kind": kind, "occurred_at": at, "outcome": outcome}


def _open_with_three_members(cohort="coh-1"):
    rows = [
        _cev("opened", at=T0, cohort=cohort),
        _cev("member_joined", at=T0 + timedelta(seconds=1), cohort=cohort, pid="pi-a", pack="wire-repair-standard",
             ver="1.0.0", mcid="cid-a"),
        _cev("member_joined", at=T0 + timedelta(seconds=2), cohort=cohort, pid="pi-b", pack="wire-repair-agentic",
             ver="1.0.0", mcid="cid-b"),
        _cev("member_joined", at=T0 + timedelta(seconds=3), cohort=cohort, pid="pi-c", pack="wire-repair-standard",
             ver="1.0.0", mcid="cid-c"),
    ]
    # one completed, one failed, one still running
    outcomes = [
        _audit("cid-a", "dispatch_accepted", T0 + timedelta(seconds=1)),
        _audit("cid-a", "process_completed", T0 + timedelta(seconds=20), outcome="End_Resolved"),
        _audit("cid-b", "dispatch_accepted", T0 + timedelta(seconds=2)),
        _audit("cid-b", "process_failed", T0 + timedelta(seconds=15)),
        _audit("cid-c", "dispatch_accepted", T0 + timedelta(seconds=3)),  # no terminal → running
    ]
    return rows, outcomes


def test_cohort_list_rollup_joins_member_outcomes():
    rows, outcomes = _open_with_three_members()
    lst = build_cohort_list(rows, outcomes)
    assert len(lst) == 1
    c = lst[0]
    assert c["cohort_instance_id"] == "coh-1"
    assert c["cohort_def_id"] == "wire_transfer_cohort" and c["correlation_value"] == "1v23p"
    assert c["state"] == "open"
    assert c["member_count"] == 3
    assert c["rollup"] == {"done": 1, "failed": 1, "running": 1}   # joined from member outcomes
    assert c["anomalies"] == 0
    assert c["opened_at"] == T0 and c["closed_at"] is None and c["outcome"] is None


def test_cohort_list_closed_with_outcome_and_late_join_anomaly():
    rows, outcomes = _open_with_three_members()
    rows.append(_cev("late_join", at=T0 + timedelta(seconds=5), pid="pi-late", pack="wire-repair-standard",
                     ver="1.0.0", mcid="cid-late", detail="member joined after cohort was closed"))
    rows.append(_cev("closing", at=T0 + timedelta(seconds=25), outcome="process_ended"))
    rows.append(_cev("closed", at=T0 + timedelta(seconds=30), outcome="process_ended"))
    c = build_cohort_list(rows, outcomes)[0]
    assert c["state"] == "closed"
    assert c["outcome"] == "process_ended"
    assert c["closed_at"] == T0 + timedelta(seconds=30)
    assert c["anomalies"] == 1                                     # the late_join
    assert c["member_count"] == 3                                  # member_joined only (late excluded)


def test_cohort_detail_roster_events_and_close():
    rows, outcomes = _open_with_three_members()
    rows.append(_cev("late_join", at=T0 + timedelta(seconds=5), pid="pi-late", pack="wire-repair-standard",
                     ver="2.0.0", mcid="cid-late"))
    rows.append(_cev("closed", at=T0 + timedelta(seconds=30), outcome="process_ended"))
    detail = build_cohort_detail(rows, outcomes)

    assert detail["state"] == "closed" and detail["close"]["signalled"] is True
    assert detail["close"]["outcome"] == "process_ended" and detail["close"]["late_joins"] == 1

    roster = {m["process_instance_id"]: m for m in detail["roster"]}
    assert set(roster) == {"pi-a", "pi-b", "pi-c", "pi-late"}      # member_joined ∪ late_join
    assert roster["pi-a"]["status"] == "done" and roster["pi-a"]["outcome"] == "End_Resolved"
    assert roster["pi-a"]["started_at"] == T0 + timedelta(seconds=1)
    assert roster["pi-b"]["status"] == "failed"
    assert roster["pi-c"]["status"] == "running" and roster["pi-c"]["ended_at"] is None
    assert roster["pi-late"]["late"] is True and roster["pi-late"]["pack_version"] == "2.0.0"

    ops = [e["op"] for e in detail["events"]]                      # ordered by occurred_at
    assert ops == ["opened", "member_joined", "member_joined", "member_joined", "late_join", "closed"]


def test_cohort_detail_empty_rows_is_none():
    assert build_cohort_detail([], []) is None


def test_cohort_list_orders_newest_opened_first():
    a, oa = _open_with_three_members("coh-old")
    b, ob = _open_with_three_members("coh-new")
    for r in b:
        r["occurred_at"] = r["occurred_at"] + timedelta(hours=1)   # newer
    lst = build_cohort_list(a + b, oa + ob)
    assert [c["cohort_instance_id"] for c in lst] == ["coh-new", "coh-old"]
