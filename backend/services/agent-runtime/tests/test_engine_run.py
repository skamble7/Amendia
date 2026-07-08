# tests/test_engine_run.py
"""Parts C+D end-to-end at the graph level (MemorySaver, no Mongo).

Drives the compiled wire-repair graph through the HITL gates and asserts the
artifacts, actor_log sequence, and gate payloads per mode.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.engine.compiler import compile_graph
from app.engine.executor import Executor
from app.engine.state import initial_state
from tests._wire import default_decision, drive, make_envelope, run_to_first_gate


def _app():
    from app.config import settings
    from app.engine.bundle import PackBundle
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    return compile_graph(b, Executor(), simulation=True, checkpointer=MemorySaver())


def _initial(reason_code, exception_id="EXC-T-1"):
    env = make_envelope(reason_code, exception_id=exception_id)
    return initial_state(
        envelope=env,
        trace={"correlation_id": exception_id},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )


def test_ac01_runs_to_resolved_with_expected_artifacts_and_gates():
    app = _app()
    cfg = {"configurable": {"thread_id": "t-ac01"}}
    result, gates = drive(app, cfg, _initial("AC01", "EXC-AC01"))

    assert result["outcome"] == "End_Resolved"
    # all expected artifacts present
    assert set(result["artifacts"]) >= {"dossier", "beneficiary", "repair", "screening", "resolution"}
    assert result["artifacts"]["beneficiary"]["repair_verdict"] == "repairable"

    # the four HITL modes were all exercised on this path
    gate_elements = [g["element_id"] for g in gates]
    assert gate_elements == [
        "Task_AssessRepairability",   # review_after
        "Task_DraftRepair",           # review_after
        "Task_ApproveRepair",         # manual
        "Task_SanctionsRescreen",     # approve_result
        "Task_ApplyRepair",           # approve_actions
        "Task_NotifyParties",         # approve_actions
    ]
    modes = {g["element_id"]: g["hitl_mode"] for g in gates}
    assert modes["Task_ApplyRepair"] == "approve_actions"
    assert any(g.get("proposed_actions") for g in gates if g["element_id"] == "Task_ApplyRepair")

    # actor_log: humans recorded with the right users; SoD-relevant distinct actors
    humans = [(e["element_id"], e["actor"]) for e in result["actor_log"] if e["kind"] == "human"]
    assert ("Task_DraftRepair", "analyst-1") in humans
    assert ("Task_ApproveRepair", "approver-1") in humans


def test_be04_reaches_obtain_info_manual_gate():
    app = _app()
    cfg = {"configurable": {"thread_id": "t-be04"}}
    # BE04 → needs_info; first gate is the assess review, then after approving it,
    # the gateway routes to the ObtainInfo manual task.
    result = app.invoke(_initial("BE04", "EXC-BE04"), cfg)
    assert "__interrupt__" in result
    first = result["__interrupt__"][0].value
    assert first["element_id"] == "Task_AssessRepairability"
    # approve the verdict → routes to ObtainInfo (manual)
    result = app.invoke(Command(resume=default_decision(first)), cfg)
    assert "__interrupt__" in result
    second = result["__interrupt__"][0].value
    assert second["element_id"] == "Task_ObtainInfo"
    assert second["hitl_mode"] == "manual"


def test_sanctioned_creditor_blocks_apply_via_reject():
    # A sanctions hit lets the approver reject the apply-actions gate → instance fails.
    from app.config import settings
    from app.engine.bundle import PackBundle
    app = compile_graph(
        PackBundle.from_seed_dir(settings.SEED_DIR), Executor(), simulation=True,
        checkpointer=MemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "t-sanction"}}
    env = make_envelope("AC01", exception_id="EXC-SANC", creditor_name="SANCTIONED HOLDINGS")
    init = initial_state(envelope=env, trace={"correlation_id": "EXC-SANC"},
                         pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"})

    result = app.invoke(init, cfg)
    # walk gates, approving everything until the apply gate, which we reject
    import pytest
    with pytest.raises(Exception):
        steps = 0
        while "__interrupt__" in result:
            steps += 1
            assert steps < 30
            payload = result["__interrupt__"][0].value
            if payload["element_id"] == "Task_ApplyRepair":
                decision = {"decision": "reject", "decided_by": "approver-1"}
            else:
                decision = default_decision(payload)
            result = app.invoke(Command(resume=decision), cfg)
    # screening recorded the hit before the apply gate
    state = app.get_state(cfg).values
    assert state["artifacts"]["screening"]["verdict"] == "hit"
