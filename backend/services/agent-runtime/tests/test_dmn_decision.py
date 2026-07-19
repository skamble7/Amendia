# tests/test_dmn_decision.py
"""ADR-037 — native DMN decision capability in the agent-runtime.

End-to-end: a `businessRuleTask` bound to a `kind: decision` capability evaluates its inline table,
emits a schema-validated verdict artifact, and a downstream gateway routes on the verdict. Plus the
executor-level guarantee that a runtime hit-policy violation is a *technical* CapabilityError, not a
modeled business error (never routed to an error boundary).
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

DMN_SEED = str(settings.SEED_DIR).replace("wire-repair-standard", "wire-repair-dmn")


def _graph():
    b = PackBundle.from_seed_dir(DMN_SEED)
    return compile_graph(b, InProcessExecutor(), simulation=True,
                         checkpointer=MemorySaver(), profile="common_executable")


def _run(app, *, amount, tid):
    env = make_envelope("AC01")
    env["payment"]["settlement_amount"]["value"] = amount
    init = initial_state(envelope=env, trace={"correlation_id": "c"},
                         pack={"pack_key": "wire-repair-dmn", "pack_version": "1.0.0"})
    final, _ = drive(app, {"configurable": {"thread_id": tid}}, init)
    return final


# --------------------------------------------------------------------------- #
# End-to-end: businessRuleTask(decision) → verdict artifact → gateway routing
# --------------------------------------------------------------------------- #
def test_decision_pack_builds_with_decision_kind():
    b = PackBundle.from_seed_dir(DMN_SEED)
    assert b.descriptors["cap.dmn.repair_decision"].kind.value == "decision"


def test_e2e_auto_repair_route():
    final = _run(_graph(), amount=250000.0, tid="dmn-auto")
    assert final["artifacts"]["decision"] == {"verdict": "auto_repair"}   # schema-validated verdict
    assert final["outcome"] == "End_Auto"                                 # gateway routed on the verdict
    # the businessRuleTask acted as a capability in the audit log
    assert any(e["element_id"] == "Task_Decide" for e in final["actor_log"])


def test_e2e_manual_review_route_default_branch():
    final = _run(_graph(), amount=2_000_000.0, tid="dmn-review")
    assert final["artifacts"]["decision"] == {"verdict": "manual_review"}
    assert final["outcome"] == "End_Review"


# --------------------------------------------------------------------------- #
# Executor: hit-policy violation is a TECHNICAL failure (not a boundary route)
# --------------------------------------------------------------------------- #
def _decision_descriptor(table) -> CapabilityDescriptor:
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": "cap.dmn.x", "version": "1.0.0",
        "title": "x", "kind": "decision", "side_effect": "read_only",
        "inputs": [{"name": "f", "schema": "art.dmn.facts@^1.0.0"}],
        "outputs": [{"name": "decision", "schema": "art.dmn.verdict@^1.0.0"}],
        "runtime": {"kind": "decision", "table": table}, "status": "active",
    })


def _ctx():
    return ExecutionContext(envelope={}, mode="execute", simulation=True,
                            extras={"output_schemas": {}})


def test_execute_decision_produces_verdict():
    d = _decision_descriptor({
        "hit_policy": "FIRST",
        "inputs": [{"expression": "f.tier"}],
        "outputs": [{"name": "verdict"}],
        "rules": [{"when": ['"gold"'], "then": ["fast"]}, {"when": ["-"], "then": ["slow"]}],
    })
    out = execute_capability(d, {"f": {"tier": "gold"}}, _ctx())
    assert out["outputs"]["art.dmn.verdict"] == {"verdict": "fast"}
    assert "decision" in out["log"]


def test_execute_decision_unique_conflict_is_technical_error():
    d = _decision_descriptor({
        "hit_policy": "UNIQUE",
        "inputs": [{"expression": "f.tier"}],
        "outputs": [{"name": "verdict"}],
        "rules": [{"when": ["-"], "then": ["a"]}, {"when": ['"gold"'], "then": ["b"]}],
    })
    with pytest.raises(CapabilityError) as ei:
        execute_capability(d, {"f": {"tier": "gold"}}, _ctx())
    # crucially NOT a CapabilityBusinessError — a misconfigured table is a bug, not a modeled outcome
    assert not isinstance(ei.value, CapabilityBusinessError)


def test_execute_decision_no_match_is_technical_error():
    d = _decision_descriptor({
        "hit_policy": "FIRST",
        "inputs": [{"expression": "f.tier"}],
        "outputs": [{"name": "verdict"}],
        "rules": [{"when": ['"gold"'], "then": ["b"]}],
    })
    with pytest.raises(CapabilityError):
        execute_capability(d, {"f": {"tier": "bronze"}}, _ctx())
