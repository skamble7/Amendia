# tests/test_fresh_domain_neutrality.py
"""ADR-047 neutrality invariant (runtime half) — a fresh domain executes on the GENERIC platform.

Executes ``widget-qa`` — a brand-new domain (manufacturing QA, ``cap.widgetqa.*`` / ``art.widgetqa.*``, zero
payments overlap) — end-to-end on the unchanged runtime: the generic compiler + the generic stub stack
(``stub_executor``), with the pack's MCP tools injected as fixture callables (exactly how a real MCP server's
tools would be brokered). Both gateway branches are driven to a terminal outcome.

The pack is pure fixture data (no Python) and no ``app/`` file changes — that is the proof that a new domain
needs DATA, not code. The registry half (``process-registry/tests/test_fresh_domain_neutrality.py``) proves
the same pack onboards→validates→activates; together they span the registry→runtime seam.
"""
from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.state import initial_state
from tests._stub_stack import stub_executor
from tests._wire import drive

WIDGET_QA = Path(__file__).resolve().parent / "fixtures" / "widget-qa"


def _tools():
    """The widget-qa MCP server's tools as in-process callables. `inspect_widget` grades a widget (a
    `DEFECT`-marked id fails, mirroring the marker-based screen stub); `certify_widget` issues a cert."""
    def inspect_widget(args):
        wid = str((args or {}).get("widget") or "")
        fail = "DEFECT" in wid.upper()
        return {"grade": "fail" if fail else "pass", "defect_count": 3 if fail else 0,
                "notes": "marker-based QA stub"}

    def certify_widget(args):
        return {"certificate_id": "CERT-WGT-1", "certified_batch": "BATCH-2026-07"}

    return {"inspect_widget": inspect_widget, "certify_widget": certify_widget}


def _app():
    bundle = PackBundle.from_seed_dir(str(WIDGET_QA))
    return compile_graph(bundle, stub_executor(tools=_tools()), simulation=True,
                         checkpointer=MemorySaver())


def _initial(widget_id: str, wo: str):
    return initial_state(
        envelope={"widget_id": widget_id, "batch_id": "BATCH-2026-07", "line": "assembly-3"},
        trace={"correlation_id": wo},
        pack={"pack_key": "widget-qa", "pack_version": "1.0.0"})


def test_fresh_domain_pass_branch_certifies():
    # a clean widget → inspect(pass) → gateway → certify → End_Certified, on the generic platform.
    result, gates = drive(_app(), {"configurable": {"thread_id": "wq-pass"}},
                          _initial("WGT-000123", "wo-pass"))
    assert result["outcome"] == "End_Certified", result["outcome"]
    assert result["artifacts"]["inspection"]["grade"] == "pass"
    assert result["artifacts"]["certificate"]["certificate_id"] == "CERT-WGT-1"


def test_fresh_domain_fail_branch_rejects():
    # a defective widget → inspect(fail) → gateway default → End_Rejected, no certificate.
    result, gates = drive(_app(), {"configurable": {"thread_id": "wq-fail"}},
                          _initial("WGT-DEFECT-9", "wo-fail"))
    assert result["outcome"] == "End_Rejected", result["outcome"]
    assert result["artifacts"]["inspection"]["grade"] == "fail"
    assert "certificate" not in result["artifacts"]


def test_platform_carries_no_widgetqa_code():
    # The enforceable "data, not code" guard (more robust than a git diff): the runtime app/ image contains
    # ZERO widget-qa-specific code. If a new domain ever required an app/ change, this fails.
    app_dir = Path(__file__).resolve().parent.parent / "app"
    hits = [str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
            if "widgetqa" in p.read_text().lower() or "widget_qa" in p.read_text().lower()]
    assert not hits, f"platform image references the fresh domain — it should need no code: {hits}"
