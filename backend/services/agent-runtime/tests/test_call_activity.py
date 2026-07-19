# tests/test_call_activity.py
"""ADR-039 / Backlog #1 — cross-pack composition (callActivity), inline-compiled.

A caller pack's callActivity splices the pinned callee pack's graph inline — one instance, one audit
trail — with input_map/output_map IO and callee-namespace scoping. Nested (A→B→C) flattens; cycles and
excess depth are refused.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.call_activity import CallActivityError, flatten_call_activities
from app.engine.compiler import CompilerError, compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.state import initial_state
from tests._wire import drive, make_envelope

SEED = Path(settings.SEED_DIR).parent  # the seed/ root (holds all compose-* packs)


def _provider(pack_key, version):
    return PackBundle.from_seed_dir(SEED / pack_key)


def _run(pack_key, tid, *, provider=_provider):
    b = PackBundle.from_seed_dir(SEED / pack_key)
    app = compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable", bundle_provider=provider)
    init = initial_state(envelope=make_envelope("AC01"), trace={"correlation_id": "c"},
                         pack={"pack_key": pack_key, "pack_version": "1.0.0"})
    return drive(app, {"configurable": {"thread_id": tid}}, init)[0]


# --------------------------------------------------------------------------- #
# Inline happy path
# --------------------------------------------------------------------------- #
def test_inline_happy_path():
    final = _run("compose-caller", "cc-happy")
    assert final["outcome"] == "E"
    # input_map (inp <- seed) fed the callee; the callee ran (n+1, /leaf); output_map (got <- leafout)
    # landed it in caller state; the caller continued and consumed it downstream (Task_Finish).
    assert final["artifacts"]["got"] == {"n": 11, "tag": "caller/leaf"}
    assert final["artifacts"]["final"] == {"n": 111, "tag": "caller/leaf/final"}


def test_callee_artifacts_are_scoped_no_collision():
    final = _run("compose-caller", "cc-scope")
    # callee-internal artifacts live under the callActivity-scoped namespace, not the bare binding names
    assert "CA_Leaf__inp" in final["artifacts"] and "CA_Leaf__leafout" in final["artifacts"]
    assert "inp" not in final["artifacts"] and "leafout" not in final["artifacts"]


def test_one_instance_one_actor_log_both_packs():
    final = _run("compose-caller", "cc-log")
    acted = {e["element_id"] for e in final["actor_log"]}
    assert {"Task_Seed", "Task_Finish"} <= acted        # caller entries
    assert "CA_Leaf__Task_Leaf" in acted                # callee (scoped) entry — same instance/log
    assert any(e.get("kind") == "call" for e in final["actor_log"])  # the boundary map audit entries


# --------------------------------------------------------------------------- #
# Nested (acyclic) — A calls B calls C
# --------------------------------------------------------------------------- #
def test_nested_three_levels_flattens_and_runs():
    final = _run("compose-top", "nested")
    assert final["outcome"] == "E"
    # top(1) → mid(+2) → leaf(+1) = 4; tag composed across all three packs, in order.
    assert final["artifacts"]["topout"] == {"n": 4, "tag": "top/mid/leaf"}
    # doubly-scoped keys prove nested namespacing (CA_TopMid / CA_MidLeaf)
    assert any(k.startswith("CA_TopMid__CA_MidLeaf__") for k in final["artifacts"])


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #
def test_cycle_refused():
    b = PackBundle.from_seed_dir(SEED / "compose-cyc-a")
    with pytest.raises(CompilerError, match="cycle"):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable", bundle_provider=_provider)


def test_depth_refused():
    b = PackBundle.from_seed_dir(SEED / "compose-top")  # top → mid → leaf (depth 2)
    with pytest.raises(CallActivityError, match="depth"):
        flatten_call_activities(b, _provider, call_stack=("compose-top",), depth=0, max_depth=1)


def test_composite_without_provider_refused():
    b = PackBundle.from_seed_dir(SEED / "compose-caller")
    with pytest.raises(CompilerError):
        compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                      profile="common_executable", bundle_provider=None)


# --------------------------------------------------------------------------- #
# Pinning / reproducibility — the callee version pinned in resolution is used
# --------------------------------------------------------------------------- #
def test_pinned_callee_version_from_resolution_is_used():
    b = PackBundle.from_seed_dir(SEED / "compose-caller")
    # simulate an activation pin of the callee at an exact version
    b.resolution["call_activities"] = [{"element": "CA_Leaf", "pack_key": "compose-leaf", "version": "1.0.0"}]
    seen = {}

    def pinning_provider(pack_key, version):
        seen[pack_key] = version
        return PackBundle.from_seed_dir(SEED / pack_key)

    compile_graph(b, InProcessExecutor(), simulation=True, checkpointer=MemorySaver(),
                  profile="common_executable", bundle_provider=pinning_provider)
    assert seen["compose-leaf"] == "1.0.0"  # the pinned exact version, not the "^1.0.0" range
