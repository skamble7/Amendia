# tests/test_rework_loop_agentic.py
"""ADR-019 §rework loops (agentic) — the needs-info loop must terminate on wire-repair-agentic too.

Agentic is NOT a copy of standard: its Assess is a `deep_agent` (`cap.payment.assess_beneficiary_agentic`)
producing `art.payment.repair_verdict`, with no MCP stub to map ``resolution → verdict``. The mapping lives in
the capability's prompt (prod) and its CI analog (``WireAgenticDeepAgentRunner`` — reuses the standard assess
handler for identical semantics). The human's disposition reaches the deep-agent as an ADR-048 optional input
(``info_resolution``, absent-tolerant): ``resolved`` ⇒ repairable ⇒ End_Resolved, ``cannot_obtain`` ⇒
unrepairable ⇒ End_Returned. On the first pass (no Obtain-Info) the input is null → reason codes drive
(BE04 → needs_info).

Asserts VERDICT CONTENT (``art.payment.repair_verdict.repair_verdict``) + that ``info_resolution`` was committed
and survived resume — not merely that a verdict artifact exists (the gap that let standard ship a spinning loop
while green). ``max_steps`` is the loop guard.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor.memo import InMemoryMemoStore
from app.engine.state import initial_state
from tests._stub_stack import stub_executor
from tests._wire import default_decision, make_envelope

PK, PV = "wire-repair-agentic", "1.0.0"


def _resolve_at_obtaininfo(outcome: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def decide(payload: Dict[str, Any]) -> Dict[str, Any]:
        d = default_decision(payload)
        if payload.get("element_id") == "Task_ObtainInfo":
            d["edits"] = {"info_resolution": {"outcome": outcome, "details": "analyst note for the audit trail"}}
        return d
    return decide


def _drive(outcome: str, thread: str):
    bundle = PackBundle.from_seed_dir(f"seed/{PK}")
    ex = stub_executor(memo=InMemoryMemoStore(), memoize=True)  # memo ON — the frozen-loop hazard is live
    app = compile_graph(bundle, ex, simulation=True, checkpointer=MemorySaver())
    env = make_envelope("BE04", exception_id="EXC-AG-REWORK")  # BE04 → needs_info on the first pass
    state = initial_state(envelope=env, trace={"correlation_id": "EXC-AG-REWORK"},
                          pack={"pack_key": PK, "pack_version": PV})
    cfg = {"configurable": {"thread_id": thread}}
    decide = _resolve_at_obtaininfo(outcome)
    gates = []
    result = app.invoke(state, cfg)
    for _ in range(20):  # loop guard — a non-terminating loop trips this and fails loudly
        if "__interrupt__" not in result:
            break
        payload = result["__interrupt__"][0].value
        gates.append(payload["element_id"])
        result = app.invoke(Command(resume=decide(payload)), cfg)
    else:
        raise AssertionError("agentic needs-info loop did not terminate within max_steps")
    return result, gates


def test_agentic_needs_info_loop_terminates_when_analyst_supplies_info():
    result, gates = _drive("resolved", "t-ag-resolved")
    assert result["outcome"] == "End_Resolved", result.get("outcome")
    assert "Task_ObtainInfo" in gates
    assert gates.count("Task_AssessRepairability") == 2, gates   # looped exactly once
    assert gates.count("Task_ObtainInfo") == 1, gates
    assert result["artifacts"]["beneficiary"]["repair_verdict"] == "repairable"
    assert result["artifacts"]["info_resolution"]["outcome"] == "resolved"


def test_agentic_needs_info_loop_takes_human_return_exit():
    result, gates = _drive("cannot_obtain", "t-ag-return")
    assert result["outcome"] == "End_Returned", result.get("outcome")
    assert gates.count("Task_ObtainInfo") == 1, gates
    assert gates.count("Task_AssessRepairability") == 2, gates
    assert result["artifacts"]["beneficiary"]["repair_verdict"] == "unrepairable"
    assert result["artifacts"]["info_resolution"]["outcome"] == "cannot_obtain"
