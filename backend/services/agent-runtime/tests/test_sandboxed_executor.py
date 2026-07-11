# tests/test_sandboxed_executor.py
"""ADR-017 Parts C+D — the SandboxedExecutor over the deterministic FakeOpenShellClient.

Proves the seam end-to-end with no live gateway: an ``llm`` capability (Task_DraftRepair)
and the ``mcp`` capability (sanctions_screen) execute through the sandbox, schema
validation still runs, and the ``actor_log`` carries the OpenShell OTLP trace id. A final
test asserts native vs nemoclaw(fake) commit the SAME artifacts and the same actor_log
structure (modulo the added trace metadata) — the seam is transparent.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor import InProcessExecutor, SandboxedExecutor
from app.engine.executor.base import ExecutionContext
from app.engine.executor.openshell import (
    CapabilityRunSpec,
    FakeOpenShellClient,
    SandboxResult,
)
from app.engine.state import initial_state
from tests._wire import drive, make_envelope


def _bundle() -> PackBundle:
    return PackBundle.from_seed_dir(settings.SEED_DIR)


def _sandboxed_app(client=None):
    client = client or FakeOpenShellClient(simulation=True)
    ex = SandboxedExecutor(client, fallback=InProcessExecutor())
    return compile_graph(_bundle(), ex, simulation=True, checkpointer=MemorySaver())


def _native_app():
    return compile_graph(_bundle(), InProcessExecutor(), simulation=True, checkpointer=MemorySaver())


def _initial(reason_code="AC01", exception_id="EXC-SBX"):
    env = make_envelope(reason_code, exception_id=exception_id)
    return initial_state(
        envelope=env, trace={"correlation_id": exception_id},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )


# --------------------------------------------------------------------------- #
# Unit-level: the fake returns a schema-shaped SandboxResult for llm + mcp specs.
# --------------------------------------------------------------------------- #
def test_fake_client_runs_mcp_capability_and_traces():
    fake = FakeOpenShellClient(simulation=True)
    spec = CapabilityRunSpec(
        capability_id="cap.payment.sanctions_screen", kind="mcp",
        inputs={}, envelope=make_envelope("AC01"), element_id="Task_Screen",
    )
    import asyncio

    result: SandboxResult = asyncio.run(fake.run_capability(spec))
    assert result.otlp_trace_id.startswith("fake-otlp-Task_Screen-")
    assert result.outputs["art.compliance.screening_result"]["verdict"] == "clean"


def test_sandboxed_executor_llm_capability_produces_valid_artifact_with_trace():
    ex = SandboxedExecutor(FakeOpenShellClient(simulation=True), fallback=InProcessExecutor())
    b = _bundle()
    descriptor = b.descriptors["cap.payment.draft_repair"]  # kind == llm
    assert (descriptor.kind.value if hasattr(descriptor.kind, "value") else descriptor.kind) == "llm"
    schema = b.schemas["art.payment.repair_instruction@1.0.0"]
    ctx = ExecutionContext(
        envelope=make_envelope("AC01"), mode="execute", simulation=True,
        extras={"output_schemas": {"art.payment.repair_instruction": schema},
                "element_id": "Task_DraftRepair"},
    )
    out = ex.execute(descriptor, {"beneficiary": {}, "dossier": {}}, ctx)
    assert "art.payment.repair_instruction" in out["outputs"]
    assert out["exec_meta"]["via"] == "openshell"
    assert out["exec_meta"]["otlp_trace_id"].startswith("fake-otlp-Task_DraftRepair-")
    assert "via OpenShell sandbox trace=" in out["log"]


def test_skill_kind_runs_in_sandbox_with_trace():
    # ADR-020 Part E: skill kinds now run through the sandbox (worker/fake), NOT the in-process
    # fallback, so they carry a sandbox trace id. Their action stays simulated in dev.
    ex = SandboxedExecutor(FakeOpenShellClient(simulation=True), fallback=InProcessExecutor())
    b = _bundle()
    descriptor = b.descriptors["cap.payment.enrich_investigation"]  # kind == skill
    ctx = ExecutionContext(envelope=make_envelope("AC01"), mode="execute", simulation=True,
                           extras={"output_schemas": {}, "element_id": "Task_Enrich"})
    out = ex.execute(descriptor, {}, ctx)
    assert out["exec_meta"]["via"] == "openshell"
    assert out["exec_meta"]["otlp_trace_id"].startswith("fake-otlp-Task_Enrich-")
    assert "art.payment.investigation_dossier" in out["outputs"]


# --------------------------------------------------------------------------- #
# End-to-end: AC01 to End_Resolved through the sandbox, with trace ids in actor_log.
# --------------------------------------------------------------------------- #
def test_ac01_runs_to_resolved_through_sandbox_with_trace_ids():
    app = _sandboxed_app()
    cfg = {"configurable": {"thread_id": "t-sbx-ac01"}}
    result, gates = drive(app, cfg, _initial("AC01", "EXC-SBX-AC01"))

    assert result["outcome"] == "End_Resolved"
    assert set(result["artifacts"]) >= {"dossier", "beneficiary", "repair", "screening", "resolution"}

    # The llm (draft_repair → Task_DraftRepair) and mcp (sanctions → Task_SanctionsRescreen)
    # capability touches carry an OpenShell trace id; skill touches do not.
    cap_entries = [e for e in result["actor_log"] if e["kind"] == "capability"]
    traced = {e["element_id"]: e["exec_meta"]["otlp_trace_id"]
              for e in cap_entries if "exec_meta" in e}
    assert "Task_DraftRepair" in traced
    assert "Task_SanctionsRescreen" in traced
    assert all(t.startswith("fake-otlp-") for t in traced.values())


# --------------------------------------------------------------------------- #
# Invariance: native vs nemoclaw(fake) commit the same artifacts + actor_log shape.
# --------------------------------------------------------------------------- #
def _strip(actor_log):
    """Drop non-deterministic/additive fields so the two runs are comparable."""
    out = []
    for e in actor_log:
        out.append({"element_id": e["element_id"], "actor": e["actor"], "kind": e["kind"]})
    return out


def test_native_and_nemoclaw_fake_are_transparent():
    native = _native_app()
    sandboxed = _sandboxed_app()
    ncfg = {"configurable": {"thread_id": "t-inv-native"}}
    scfg = {"configurable": {"thread_id": "t-inv-sbx"}}

    n_result, _ = drive(native, ncfg, _initial("AC01", "EXC-INV"))
    s_result, _ = drive(sandboxed, scfg, _initial("AC01", "EXC-INV"))

    # Same committed artifacts.
    assert n_result["artifacts"] == s_result["artifacts"]
    assert n_result["outcome"] == s_result["outcome"] == "End_Resolved"
    # Same actor_log structure (modulo the added trace metadata + timestamps).
    assert _strip(n_result["actor_log"]) == _strip(s_result["actor_log"])
    # And native carries no exec_meta at all — byte-for-byte the old shape.
    assert all("exec_meta" not in e for e in n_result["actor_log"])
