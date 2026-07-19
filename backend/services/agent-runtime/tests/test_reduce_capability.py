# tests/test_reduce_capability.py
"""ADR-038 — collection-reduction (`reduce`) capability in the agent-runtime.

End-to-end: multi-instance "screen each party" → a list of party_results → a `reduce` capability →
a summary a gateway branches on ("is any party a hit?"). Plus the executor guarantee that a runtime
misfire (source not a list / numeric op on empty) is a *technical* CapabilityError, never a boundary
route.
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from amendia_contracts.capability import CapabilityDescriptor
from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor import InProcessExecutor
from app.engine.executor.base import CapabilityBusinessError, CapabilityError, ExecutionContext
from app.engine.executor.core import execute_capability
from app.engine.state import initial_state
from tests._wire import drive, make_envelope

SCREENING_SEED = str(settings.SEED_DIR).replace("wire-repair-standard", "wire-repair-screening")


def _graph():
    b = PackBundle.from_seed_dir(SCREENING_SEED)
    return compile_graph(b, InProcessExecutor(), simulation=True,
                         checkpointer=MemorySaver(), profile="common_executable")


def _run(app, *, creditor, tid):
    env = make_envelope("AC01", creditor_name=creditor)
    init = initial_state(envelope=env, trace={"correlation_id": "c"},
                         pack={"pack_key": "wire-repair-screening", "pack_version": "1.0.0"})
    final, _ = drive(app, {"configurable": {"thread_id": tid}}, init)
    return final


# --------------------------------------------------------------------------- #
# End-to-end: MI list → reduce → gateway (both branches)
# --------------------------------------------------------------------------- #
def test_reduce_pack_builds_with_reduce_kind():
    b = PackBundle.from_seed_dir(SCREENING_SEED)
    assert b.descriptors["cap.screening.reduce_hits"].kind.value == "reduce"


def test_e2e_any_party_hit_routes_to_hit():
    final = _run(_graph(), creditor="SANCTIONED HOLDINGS LLC", tid="red-hit")
    assert len(final["artifacts"]["screening"]) == 3          # MI produced a list of party results
    assert final["artifacts"]["summary"] == {"matched": "hit"}  # reduce collapsed the list
    assert final["outcome"] == "End_Hit"                       # gateway branched on the summary


def test_e2e_no_hit_routes_to_clean():
    final = _run(_graph(), creditor="ACME BENEFICIARY LLC", tid="red-clean")
    assert final["artifacts"]["summary"] == {"matched": None}
    assert final["outcome"] == "End_Clean"


# --------------------------------------------------------------------------- #
# Executor: op coverage + technical-error discipline
# --------------------------------------------------------------------------- #
def _reduce_descriptor(config) -> CapabilityDescriptor:
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": "cap.x.reduce", "version": "1.0.0",
        "title": "x", "kind": "reduce", "side_effect": "read_only",
        "inputs": [{"name": "s", "schema": "art.x.list@^1.0.0"}],
        "outputs": [{"name": "summary", "schema": "art.x.summary@^1.0.0"}],
        "runtime": {"kind": "reduce", "config": config}, "status": "active",
    })


def _ctx():
    return ExecutionContext(envelope={}, mode="execute", simulation=True, extras={"output_schemas": {}})


def test_execute_reduce_any_boolean():
    d = _reduce_descriptor({"op": "any", "source": "s", "item_path": "v",
                            "predicate": '= "hit"', "output_field": "matched"})
    out = execute_capability(d, {"s": [{"v": "clean"}, {"v": "hit"}]}, _ctx())
    assert out["outputs"]["art.x.summary"] == {"matched": True}
    assert "reduce" in out["log"]


def test_execute_reduce_source_not_a_list_is_technical():
    d = _reduce_descriptor({"op": "count", "source": "s", "output_field": "n"})
    with pytest.raises(CapabilityError) as ei:
        execute_capability(d, {"s": {"not": "a list"}}, _ctx())
    assert not isinstance(ei.value, CapabilityBusinessError)  # a config bug, not a modeled outcome


def test_execute_reduce_numeric_empty_is_technical():
    d = _reduce_descriptor({"op": "min", "source": "s", "item_path": "amt", "output_field": "lo"})
    with pytest.raises(CapabilityError):
        execute_capability(d, {"s": []}, _ctx())
