# tests/test_approve_actions_synthesis.py
"""ADR-047 D2 — an approve_actions gate on a side-effectful MCP capability must present the pending action to
authorize, and the tool's side effect must fire ONLY after approval.

Pre-D2 these action tasks were in-code ``skill``s whose ``propose`` returned the action list; the re-home to
generic ``mcp`` capabilities dropped propose semantics, so ``_execute_mcp_real`` returned ``proposed_actions=[]``
in every mode — the live gate opened EMPTY ("Authorize all" tripped the frontend "select ≥1 action" guard and
wedged the instance) and, worse, proposing by invoking the tool would have performed the side effect BEFORE
approval. The golden net asserts terminal outcomes, not gate CONTENTS, so it stayed green.

The fix synthesizes exactly one host-side ``ProposedAction`` for a side-effectful, non-propose-capable
capability (descriptor-sourced summary, resolved input_map arguments as ``detail``) and never touches the tool
until execute. These tests assert the CONTENT and the post-approval-only side effect on the real server handlers
(``server_tool_map``), not a fabricated payload.
"""
from __future__ import annotations

import collections

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.state import initial_state
from tests._mcp_server_tools import server_tool_map
from tests._stub_stack import stub_executor
from tests._wire import default_decision, make_envelope

PK, PV = "wire-repair-standard", "1.0.0"
_ACTION_TOOLS = ("apply_repair", "notify_parties", "execute_return")


def _counting_tools():
    """server_tool_map with the action tools wrapped to record (call-count, last-args) — so a test can prove the
    tool is invoked exactly once, and only after the gate is approved."""
    base = server_tool_map()
    calls = collections.Counter()
    seen_args: dict = {}

    def wrap(name, fn):
        def _w(args):
            calls[name] += 1
            seen_args[name] = args
            return fn(args)
        return _w

    tools = dict(base)
    for n in _ACTION_TOOLS:
        if n in base:
            tools[n] = wrap(n, base[n])
    return tools, calls, seen_args


def _drive_asserting_side_effect_after_approval(reason_code: str, exception_id: str, thread: str):
    """Drive the pack; at each approve_actions gate assert (a) ≥1 proposed action, (b) its detail is the args the
    tool will receive, (c) the tool has NOT been called yet (no premature side effect). Returns the final state,
    the per-tool call counter, and the gates seen."""
    tools, calls, seen_args = _counting_tools()
    bundle = PackBundle.from_seed_dir(f"seed/{PK}")
    app = compile_graph(bundle, stub_executor(tools=tools), simulation=True, checkpointer=MemorySaver())
    env = make_envelope(reason_code, exception_id=exception_id)
    state = initial_state(envelope=env, trace={"correlation_id": exception_id},
                          pack={"pack_key": PK, "pack_version": PV})
    cfg = {"configurable": {"thread_id": thread}}

    seen_action_nodes: list = []
    result = app.invoke(state, cfg)
    for _ in range(40):
        if "__interrupt__" not in result:
            break
        payload = result["__interrupt__"][0].value
        if payload.get("hitl_mode") == "approve_actions":
            actions = payload.get("proposed_actions") or []
            tool = payload["element_id"].replace("Task_", "").lower()
            # (a) the gate is authorizable — at least one action, never the empty deadlock.
            assert len(actions) >= 1, f"{payload['element_id']} opened with no proposed actions"
            act = actions[0]
            # (b) detail is the ACTUAL payload the tool will receive (the human authorizes the real thing).
            assert isinstance(act.get("detail"), dict) and act["detail"], act
            assert act.get("summary"), "summary must be descriptor-sourced, not empty"
            # (c) the side effect has NOT fired during propose.
            assert calls[act["kind"]] == 0, f"{act['kind']} was called BEFORE approval (premature side effect)"
            seen_action_nodes.append((payload["element_id"], act))
        result = app.invoke(Command(resume=default_decision(payload)), cfg)

    return result, calls, seen_args, seen_action_nodes


def test_repairable_branch_action_gates_are_populated_and_side_effect_after_approval():
    result, calls, seen_args, nodes = _drive_asserting_side_effect_after_approval(
        "AC01", "EXC-ACTS-AC01", "t-acts-ac01")
    assert result["outcome"] == "End_Resolved", result.get("outcome")
    # the repairable branch authorizes ApplyRepair then NotifyParties.
    ids = [n[0] for n in nodes]
    assert ids == ["Task_ApplyRepair", "Task_NotifyParties"], ids
    # each tool fired exactly once — after its gate, never during propose.
    assert calls["apply_repair"] == 1 and calls["notify_parties"] == 1, dict(calls)
    # the detail the human saw is exactly what the tool received on execute.
    for node_id, act in nodes:
        assert act["detail"] == seen_args[act["kind"]], (node_id, act["detail"], seen_args[act["kind"]])
    # the synthesized summary is the descriptor's registered title, not a hardcoded business noun.
    summaries = {n[1]["kind"]: n[1]["summary"] for n in nodes}
    assert summaries["apply_repair"] == "Apply repair & release payment"
    assert summaries["notify_parties"] == "Notify originator & beneficiary bank"


def test_unrepairable_branch_execute_return_gate_is_populated_and_authorizes():
    # AC06 → unrepairable → return path: Task_ExecuteReturn is the same side-effectful approve_actions class,
    # so it must authorize and complete too (scope: not only NotifyParties).
    result, calls, seen_args, nodes = _drive_asserting_side_effect_after_approval(
        "AC06", "EXC-ACTS-AC06", "t-acts-ac06")
    assert result["outcome"] == "End_Returned", result.get("outcome")
    assert "Task_ExecuteReturn" in [n[0] for n in nodes]
    assert calls["execute_return"] == 1, dict(calls)
