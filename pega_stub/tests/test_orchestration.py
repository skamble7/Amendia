# tests/test_orchestration.py
"""The A → B → C → close orchestration state machine + idempotency (pure orchestrator + the app endpoints)."""
from __future__ import annotations

from pega_stub import scenarios as S
from pega_stub.orchestrator import Orchestrator


async def _instant(_delay):
    """A no-op sleep so the delayed closeout fires deterministically in tests (no real 25s wait)."""
    return


def _types(store):
    return [s["trigger_type"] for s in store.submitted]


def _case_ids(store):
    return {s["payload"]["case_id"] for s in store.submitted}


# --------------------------------------------------------------------------- #
# Orchestrator (pure)
# --------------------------------------------------------------------------- #
async def test_start_case_fires_segment_a(orch, store):
    case = await orch.start_case("credit_approve", case_id="case-1")
    assert case["status"] == "running" and case["step"] == "A"
    assert _types(store) == ["ach.assess_exposure_requested"]
    a = store.submitted[0]["payload"]
    assert a["request_type"] == S.REQ_ASSESS and a["case_id"] == "case-1" and a["exposure_type"] == "credit"


async def test_full_run_advances_a_b_c_close_same_case_id(orch, store):
    await orch.start_case("credit_approve", case_id="case-1")
    # Segment A handback recommends APPROVE → B decision approve
    await orch.handback("case-1", "A", {"recommendation": "APPROVE"})
    await orch.handback("case-1", "B", {"acknowledged": True})
    case = await orch.handback("case-1", "C", {"applied": True})

    assert _types(store) == [
        "ach.assess_exposure_requested", "ach.enforce_decision_requested",
        "ach.closeout_requested", "ach.process_completed",
    ]
    assert _case_ids(store) == {"case-1"}                      # every message carries the same case_id
    assert case["status"] == "closed" and case["step"] == "closed"

    b = store.submitted[1]["payload"]; c = store.submitted[2]["payload"]; close = store.submitted[3]["payload"]
    assert b["request_type"] == S.REQ_ENFORCE and b["rbo_decision"] == "approve"
    assert c["request_type"] == S.REQ_CLOSEOUT and c["instruction"] == "release"
    assert close == {"event": "process_completed", "case_id": "case-1", "outcome": "Released"}


async def test_reject_path_purges(orch, store):
    await orch.start_case("debit_reject", case_id="case-2")
    await orch.handback("case-2", "A", {"recommendation": "REJECT"})
    await orch.handback("case-2", "B", {})
    await orch.handback("case-2", "C", {})
    assert store.submitted[1]["payload"]["rbo_decision"] == "reject"
    assert store.submitted[2]["payload"]["instruction"] == "purge"
    assert store.submitted[3]["payload"]["outcome"] == "Purged"


async def test_route_uw_uses_scenario_preset_when_recommendation_not_decisive(orch, store):
    await orch.start_case("route_uw", case_id="case-3")
    await orch.handback("case-3", "A", {"recommendation": "ROUTE_UW"})   # not decisive → preset (approve)
    assert store.submitted[1]["payload"]["rbo_decision"] == "approve"


async def test_handback_is_idempotent_per_segment(orch, store):
    await orch.start_case("credit_approve", case_id="case-4")
    await orch.handback("case-4", "A", {"recommendation": "APPROVE"})    # → submits B
    await orch.handback("case-4", "A", {"recommendation": "APPROVE"})    # duplicate A → no-op
    assert _types(store) == ["ach.assess_exposure_requested", "ach.enforce_decision_requested"]  # B once, not C


async def test_missing_segment_advances_the_next_expected(orch, store):
    await orch.start_case("credit_approve", case_id="case-5")
    await orch.handback("case-5", None, {"recommendation": "APPROVE"})   # no segment → advance A
    assert _types(store)[-1] == "ach.enforce_decision_requested"


async def test_handback_for_unknown_case_is_none(orch):
    assert await orch.handback("nope", "A", {}) is None


async def test_closed_case_ignores_further_handbacks(orch, store):
    await orch.start_case("credit_approve", case_id="case-6")
    for seg in ("A", "B", "C"):
        await orch.handback("case-6", seg, {})
    n = len(store.submitted)
    await orch.handback("case-6", "C", {})   # after close → no-op
    assert len(store.submitted) == n


# --------------------------------------------------------------------------- #
# ADR-064 SLA e2e — the late_closeout scenario (delayed Segment C → SLA breach)
# --------------------------------------------------------------------------- #
async def test_non_delayed_scenarios_fire_c_immediately(orch, store):
    # the three existing presets declare no delay → C fires synchronously on the B handback (unchanged).
    await orch.start_case("credit_approve", case_id="case-imm")
    await orch.handback("case-imm", "A", {"recommendation": "APPROVE"})
    await orch.handback("case-imm", "B", {})
    assert _types(store)[-1] == "ach.closeout_requested"      # present right after the B handback returns


async def test_late_closeout_defers_segment_c_then_closes(store):
    orch = Orchestrator(submit=store.submit, sleep=_instant)
    await orch.start_case("late_closeout", case_id="case-late")
    await orch.handback("case-late", "A", {"recommendation": "APPROVE"})
    case = await orch.handback("case-late", "B", {"acknowledged": True})

    # C is NOT fired synchronously on the B handback — it is scheduled (breaches the arrival SLA first).
    assert _types(store) == ["ach.assess_exposure_requested", "ach.enforce_decision_requested"]
    assert case["step"] == "C_pending" and case["closeout_delay_seconds"] == 25

    await orch.drain()                                        # the scheduled task fires C
    assert _types(store)[-1] == "ach.closeout_requested"
    assert store.submitted[2]["payload"]["instruction"] == "release"

    # C handback → the close still fires and the cohort drains to closed (close path unchanged).
    closed = await orch.handback("case-late", "C", {"applied": True})
    assert closed["status"] == "closed" and closed["step"] == "closed"
    assert store.submitted[3]["payload"] == {"event": "process_completed", "case_id": "case-late", "outcome": "Released"}


async def test_late_closeout_schedules_c_exactly_once(store):
    orch = Orchestrator(submit=store.submit, sleep=_instant)
    await orch.start_case("late_closeout", case_id="c9")
    await orch.handback("c9", "A", {"recommendation": "APPROVE"})
    await orch.handback("c9", "B", {})
    await orch.handback("c9", "B", {})                        # duplicate B handback → no second schedule
    await orch.drain()
    assert _types(store).count("ach.closeout_requested") == 1


async def test_late_closeout_selectable_via_api(client):
    assert "late_closeout" in (await client.get("/scenarios")).json()["scenarios"]
    r = await client.post("/cases", json={"case_id": "case-sel", "scenario": "late_closeout"})
    assert r.status_code == 201 and r.json()["step"] == "A"   # Segment A only; no delay involved yet


# --------------------------------------------------------------------------- #
# App endpoints
# --------------------------------------------------------------------------- #
async def test_endpoints_start_list_and_handback(client, store):
    r = await client.post("/cases", json={"case_id": "case-e2e", "scenario": "credit_approve"})
    assert r.status_code == 201 and r.json()["step"] == "A"

    lst = (await client.get("/cases")).json()["cases"]
    assert any(c["case_id"] == "case-e2e" for c in lst)

    r2 = await client.post("/amendia/handback", json={"case_id": "case-e2e", "segment": "A",
                                                      "result": {"recommendation": "APPROVE"}})
    assert r2.status_code == 200 and r2.json()["step"] == "B"
    assert _types(store) == ["ach.assess_exposure_requested", "ach.enforce_decision_requested"]


async def test_unknown_scenario_422_and_unknown_case_404(client):
    assert (await client.post("/cases", json={"scenario": "bogus"})).status_code == 422
    assert (await client.post("/amendia/handback", json={"case_id": "ghost"})).status_code == 404


async def test_health_and_index(client):
    assert (await client.get("/health")).json()["status"] == "ok"
    body = (await client.get("/")).text
    assert "Mock Pega" in body
