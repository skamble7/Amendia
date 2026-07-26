# tests/test_build_executor_wiring.py
"""Regression — the PRODUCTION composition root wires the D2 capability stack.

Every other suite injects the executor via ``tests/_stub_stack`` (``stub_executor`` etc.), so none of them
exercises ``factory.build_executor`` — the path ``main.py`` actually uses. That gap let the D2 flip ship an
executor with ``mcp_client=None``: post-D2 an ``mcp`` capability fails closed, so a wire-repair instance died
on its first node (``Task_EnrichPayment``) before any HITL gate, and no task ever reached the inbox — while
every test stayed green.

These tests drive real packs through ``build_executor(settings)`` (the real root), swapping ONLY the MCP
transport (``build_mcp_client`` → an in-process client over the server's own tools) so no live MCP server is
needed. They assert the wired executor reaches its first HITL gate (a wire pack) and runs a fresh domain to a
terminal outcome (widget-qa) — so the factory can never again silently diverge from the harness.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor import factory
from app.engine.executor.factory import build_executor
from app.engine.executor.mcp_client import InProcessMcpClient
from app.engine.state import initial_state
from tests._mcp_server_tools import server_tool_map
from tests._wire import make_envelope

WIDGET_QA = Path(__file__).resolve().parent / "fixtures" / "widget-qa"


def _widget_tools():
    def inspect_widget(args):
        return {"grade": "pass", "defect_count": 0, "notes": "ok"}

    def certify_widget(args):
        return {"certificate_id": "CERT-WGT-1", "certified_batch": "BATCH-2026-07"}

    return {"inspect_widget": inspect_widget, "certify_widget": certify_widget}


@pytest.fixture
def wired_factory(monkeypatch):
    # Swap ONLY the MCP transport the factory wires — the in-process client over the server's real tools
    # (+ widget-qa's fixture tools). Everything else (stub_inference, deep_agent_runner, memo) is exactly
    # what build_executor builds in production, so the composition root itself is under test.
    tools = {**server_tool_map(), **_widget_tools()}
    monkeypatch.setattr(factory, "build_mcp_client", lambda _settings: InProcessMcpClient(tools))
    return factory


def test_build_executor_reaches_first_hitl_gate(wired_factory):
    # The reported symptom, as a test: a wire-repair-standard instance must reach its first HITL gate
    # (→ a task is created), NOT fail on the first mcp node. With the pre-fix factory (mcp_client=None) this
    # raises CapabilityError on Task_EnrichPayment instead.
    ex = build_executor(settings)  # native + simulation defaults — the real root, not a harness injection
    bundle = PackBundle.from_seed_dir(settings.SEED_DIR)
    app = compile_graph(bundle, ex, simulation=True, checkpointer=MemorySaver())
    env = make_envelope("AC01", exception_id="EXC-BUILD-EXEC")
    state = initial_state(envelope=env, trace={"correlation_id": "EXC-BUILD-EXEC"},
                          pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"})

    result = app.invoke(state, {"configurable": {"thread_id": "build-exec-gate"}})

    assert "__interrupt__" in result, (
        "instance did not reach a HITL gate — build_executor produced an MCP-less executor and the pack "
        "failed on its first node (the exact D2 regression)")
    gate = result["__interrupt__"][0].value
    assert gate.get("element_id"), gate


def test_build_executor_runs_fresh_domain_to_terminal(wired_factory):
    # Neutrality guarded on the PRODUCTION wiring: the widget-qa fresh domain runs end-to-end through
    # build_executor (no HITL gates → runs to a terminal outcome), not just the test harness.
    ex = build_executor(settings)
    bundle = PackBundle.from_seed_dir(str(WIDGET_QA))
    app = compile_graph(bundle, ex, simulation=True, checkpointer=MemorySaver())
    state = initial_state(
        envelope={"widget_id": "WGT-1", "batch_id": "BATCH-2026-07", "line": "assembly-3"},
        trace={"correlation_id": "wo-build-exec"},
        pack={"pack_key": "widget-qa", "pack_version": "1.0.0"})

    result = app.invoke(state, {"configurable": {"thread_id": "build-exec-widget"}})

    assert "__interrupt__" not in result, result.get("__interrupt__")
    assert result["outcome"] == "End_Certified", result.get("outcome")
    assert result["artifacts"]["certificate"]["certificate_id"] == "CERT-WGT-1"
