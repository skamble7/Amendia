# tests/test_rework_loop.py
"""ADR-019 §rework loops — a needs-info rework loop must TERMINATE on the REAL tool behaviour, and the
analyst must have a real channel to resolve it (feed the missing info) or exit it (return the funds).

Two earlier versions each went green while the live stack looped, teaching the same lesson twice:
  1. the test fabricated ``edits.rfi.repair_hint`` the real UI never sends;
  2. the loop flipped on the mere PRESENCE of the LLM-drafted ``rfi`` artifact — but the real ``draft_rfi``
     LLM auto-filled ``rfi.repair_hint='needs_info'`` (the schema-stub omitted the optional field), which the
     assess tool's recursive ``_dig`` dug back out and used to re-steer ``needs_info`` forever.

The fix (ADR-047 D2, §C/§D of the addendum) makes the exit an EXPLICIT, human-authored artifact the LLM cannot
touch: Task_ObtainInfo produces a second output ``resolution`` (``art.payment.info_resolution``) with NO assist
draft, so the analyst must author it. ``assess_beneficiary`` keys off ``resolution.outcome``:
  * ``resolved``      → repairable   → repair path → End_Resolved   (analyst supplied the info)
  * ``cannot_obtain`` → unrepairable → return path → End_Returned   (analyst could not — the human exit, §D)

Three things make it work, verified on the REAL server handler (``server_tool_map``), not just the harness:
  * platform — the memo key is loop-visit-aware (a back-edge re-entry re-runs; a HITL replay of the same
    execution hits the memo → side-effect-once preserved); and ``_run_manual`` surfaces the no-draft output so
    the human must author it;
  * seed — Assess's input_map reads ``resolution.outcome`` via an ADR-048 optional source (null first pass);
  * tool — ``assess_beneficiary`` treats the analyst's explicit ``resolution`` as the top-precedence verdict.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Dict

from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor.memo import InMemoryMemoStore, memoized_execute
from app.engine.state import initial_state
from tests._mcp_server_tools import server_tool_map
from tests._stub_stack import stub_executor
from tests._wire import default_decision, drive, make_envelope


def _resolve_at_obtaininfo(outcome: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Drive the graph like the UI, but at Task_ObtainInfo author the human-only ``resolution`` artifact via
    ``edits`` (the drafted ``rfi`` falls through to its assist draft). This is the analyst actually resolving
    the needs-info gate — the interaction the loop's termination depends on."""
    def decide(payload: Dict[str, Any]) -> Dict[str, Any]:
        d = default_decision(payload)
        if payload.get("element_id") == "Task_ObtainInfo":
            d["edits"] = {"info_resolution": {"outcome": outcome, "details": "analyst note for the audit trail"}}
        return d
    return decide


# --------------------------------------------------------------------------- #
# Platform: the memo key is loop-visit-aware.
# --------------------------------------------------------------------------- #
def _memo_call(memo, run, *, visit):
    ctx = SimpleNamespace(mode="execute", extras={
        "process_instance_id": "pi-1", "element_id": "Task_X", "memo_attempt": 0, "memo_visit": visit,
    })
    return memoized_execute(memo=memo, enabled=True, inputs={"x": 1}, ctx=ctx, run=run)


def test_memo_reuses_within_a_visit_but_reruns_across_a_loop_visit():
    memo = InMemoryMemoStore()
    calls = {"n": 0}

    def run():
        calls["n"] += 1
        return {"outputs": {"seq": calls["n"]}}

    assert _memo_call(memo, run, visit=0)["outputs"] == {"seq": 1}
    assert _memo_call(memo, run, visit=0)["outputs"] == {"seq": 1}       # HITL replay → hit
    assert calls["n"] == 1, "same-visit replay must not re-run — the side-effect-once guarantee"
    assert _memo_call(memo, run, visit=1)["outputs"] == {"seq": 2}       # loop re-entry → miss → re-run
    assert calls["n"] == 2, "loop re-entry must re-run, not return the frozen prior artifact"


# --------------------------------------------------------------------------- #
# Tool contract (the REAL server handler): the explicit resolution outcome decides the verdict.
# --------------------------------------------------------------------------- #
def test_assess_tool_honors_explicit_resolution_outcome():
    assess = server_tool_map()["assess_beneficiary"]
    # First pass (resolution null): reason codes drive. BE04 is neither → needs_info; AC01 is repairable.
    assert assess({"reason_codes": ["BE04"], "resolution": None})["repair_verdict"] == "needs_info"
    assert assess({"reason_codes": ["AC01"]})["repair_verdict"] == "repairable"
    # After Obtain-Info: the analyst's EXPLICIT outcome is the top-precedence verdict (§C.2 / §D).
    assert assess({"reason_codes": ["BE04"], "resolution": "resolved"})["repair_verdict"] == "repairable"
    assert assess({"reason_codes": ["BE04"], "resolution": "cannot_obtain"})["repair_verdict"] == "unrepairable"
    # The resolution overrides even a first-pass repairable code — the human is the authority once they act.
    assert assess({"reason_codes": ["AC01"], "resolution": "cannot_obtain"})["repair_verdict"] == "unrepairable"


# --------------------------------------------------------------------------- #
# Integration: the loop terminates because the analyst RESOLVES it — content-asserted on the shipping path.
# --------------------------------------------------------------------------- #
def _rework_state(thread: str):
    bundle = PackBundle.from_seed_dir(settings.SEED_DIR)
    ex = stub_executor(memo=InMemoryMemoStore(), memoize=True)  # memo ON — the frozen-loop hazard is live
    app = compile_graph(bundle, ex, simulation=True, checkpointer=MemorySaver())
    env = make_envelope("BE04", exception_id="EXC-REWORK")   # BE04 → needs_info first pass
    state = initial_state(envelope=env, trace={"correlation_id": "EXC-REWORK"},
                          pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"})
    return app, state, {"configurable": {"thread_id": thread}}


def test_needs_info_loop_terminates_when_analyst_supplies_info():
    app, state, cfg = _rework_state("t-rework-resolved")
    # max_steps is the loop guard: a non-terminating loop trips it (fails loudly, never hangs).
    result, gates = drive(app, cfg, state, decide=_resolve_at_obtaininfo("resolved"), max_steps=20)
    els = [g.get("element_id") for g in gates]

    assert result["outcome"] == "End_Resolved", result.get("outcome")
    assert "Task_ObtainInfo" in els, "the needs-info branch was not exercised"
    # Looped exactly once: assess (needs_info) → ObtainInfo (analyst resolves) → assess (repairable) → onward.
    assert els.count("Task_AssessRepairability") == 2, els
    assert els.count("Task_ObtainInfo") == 1, els
    # Assert the VERDICT CONTENT, not just that an assess artifact was produced (the gap that went green while
    # looping). And the human's resolution artifact was committed and survived resume.
    assert result["artifacts"]["beneficiary"]["repair_verdict"] == "repairable"
    assert result["artifacts"]["info_resolution"]["outcome"] == "resolved"


def test_needs_info_loop_takes_human_return_exit_when_info_cannot_be_obtained():
    # §D: the analyst-controlled terminal exit — "cannot obtain → return funds" → unrepairable → End_Returned.
    app, state, cfg = _rework_state("t-rework-return")
    result, gates = drive(app, cfg, state, decide=_resolve_at_obtaininfo("cannot_obtain"), max_steps=20)
    els = [g.get("element_id") for g in gates]

    assert result["outcome"] == "End_Returned", result.get("outcome")
    assert els.count("Task_ObtainInfo") == 1, els
    assert els.count("Task_AssessRepairability") == 2, els
    assert result["artifacts"]["beneficiary"]["repair_verdict"] == "unrepairable"
    assert result["artifacts"]["info_resolution"]["outcome"] == "cannot_obtain"
