# tests/test_deep_agent.py
"""ADR-021 — the `deep_agent` capability kind (agent-runtime side).

Covers: fake execution → schema-valid repair_verdict; native fail-closed (nemoclaw-only);
mandatory memoization across a review_after resume (harness runs once; edit/reject cases);
runtime HITL enforcement; egress/tool-policy derivation. All on the FakeDeepAgentRunner /
fake OpenShell client — no harness/GPU.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from jsonschema import Draft202012Validator
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.compiler import compile_graph
from app.engine.executor import InProcessExecutor, SandboxedExecutor
from app.engine.executor.base import CapabilityError, ExecutionContext
from app.engine.executor.core import execute_capability
from app.engine.executor.deep_agent import FakeDeepAgentRunner
from app.engine.executor.memo import InMemoryMemoStore
from app.engine.executor.openshell import FakeOpenShellClient
from app.engine.executor.policy import INFERENCE_PROXY_HOST, derive_egress_policy
from app.engine.state import initial_state
from tests._wire import default_decision, make_envelope, role_user

AGENTIC_SEED = str(settings.SEED_DIR).replace("wire-repair-standard", "wire-repair-agentic")
_CAP = "cap.payment.assess_beneficiary_agentic"
_VERDICT = "art.payment.repair_verdict"


def _bundle() -> PackBundle:
    return PackBundle.from_seed_dir(AGENTIC_SEED)


def _ctx(bundle, simulation=True):
    schema = bundle.schemas[f"{_VERDICT}@1.0.0"]
    return ExecutionContext(
        envelope=make_envelope("AC01"), mode="execute", simulation=simulation,
        extras={"output_schemas": {_VERDICT: schema}, "element_id": "Task_AssessRepairability"},
    )


def _valid(bundle, produced):
    schema = bundle.schemas[f"{_VERDICT}@1.0.0"]
    assert not list(Draft202012Validator(schema).iter_errors(produced[_VERDICT]))


# --------------------------------------------------------------------------- #
# Contract: the deep_agent kind + runtime variant
# --------------------------------------------------------------------------- #
def test_contract_accepts_deep_agent_descriptor():
    from amendia_contracts.capability import CapabilityDescriptor, CapabilityKind
    d = _bundle().descriptors[_CAP]
    assert d.kind is CapabilityKind.DEEP_AGENT
    assert d.runtime.kind == "deep_agent"
    assert d.runtime.budget.max_steps >= 1


def test_contract_rejects_runtime_kind_mismatch():
    from amendia_contracts.capability import CapabilityDescriptor
    with pytest.raises(Exception):  # runtime.kind must equal top-level kind
        CapabilityDescriptor.model_validate({
            "descriptor_version": "1.0", "capability_id": "cap.payment.x_agentic", "version": "1.0.0",
            "title": "x", "kind": "deep_agent", "side_effect": "read_only", "inputs": [], "outputs": [],
            "runtime": {"kind": "llm", "prompt_key": "p"}, "status": "active",
        })


# --------------------------------------------------------------------------- #
# Fake execution + native fail-closed
# --------------------------------------------------------------------------- #
def test_fake_deep_agent_produces_schema_valid_verdict_with_evidence():
    b = _bundle()
    d = b.descriptors[_CAP]
    out = execute_capability(d, {"dossier": {}}, _ctx(b), deep_agent_runner=FakeDeepAgentRunner())
    _valid(b, out["outputs"])
    verdict = out["outputs"][_VERDICT]
    assert verdict["repair_verdict"] in ("repairable", "needs_info")
    assert verdict["evidence"], "deep_agent must produce evidence[]"
    assert "deep_agent" in out["log"]


def test_native_refuses_deep_agent_fail_closed():
    # No deep_agent runner on the native/in-process path → fail closed (nemoclaw-only).
    b = _bundle()
    d = b.descriptors[_CAP]
    with pytest.raises(CapabilityError, match="nemoclaw"):
        execute_capability(d, {"dossier": {}}, _ctx(b))  # deep_agent_runner=None
    # And through the InProcessExecutor seam:
    with pytest.raises(CapabilityError, match="nemoclaw"):
        InProcessExecutor().execute(d, {"dossier": {}}, _ctx(b))


def test_egress_policy_for_deep_agent_from_tools():
    b = _bundle()
    p = derive_egress_policy(b.descriptors[_CAP]).to_dict()
    assert p["kind"] == "deep_agent"
    assert p["inference_proxy_host"] == INFERENCE_PROXY_HOST
    assert p["agent_tools"] == ["name_match", "search_payment_history", "screen_party"]
    assert any("injected" in n or "whitelist" in n for n in p["notes"])


# --------------------------------------------------------------------------- #
# Mandatory memoization: harness runs once across a review_after resume
# --------------------------------------------------------------------------- #
class _CountingFakeClient:
    """Wraps FakeOpenShellClient, counting real deep_agent runs by element."""

    def __init__(self):
        self._inner = FakeOpenShellClient(simulation=True)
        self.calls: Dict[str, int] = {}

    async def ping(self):
        return True

    async def run_capability(self, spec):
        if spec.kind == "deep_agent":
            self.calls[spec.element_id] = self.calls.get(spec.element_id, 0) + 1
        return await self._inner.run_capability(spec)


def _graph(client, memo=None, memoize=False):
    ex = SandboxedExecutor(client, fallback=InProcessExecutor(), memo=memo, memoize=memoize)
    return compile_graph(_bundle(), ex, simulation=True, checkpointer=MemorySaver())


def _initial(exception_id="EXC-DA"):
    return initial_state(envelope=make_envelope("AC01", exception_id=exception_id),
                         trace={"correlation_id": exception_id},
                         pack={"pack_key": "wire-repair-agentic", "pack_version": "1.0.0"})


def test_sandboxed_requires_memo_for_deep_agent():
    # Fail closed if no memo store is wired for a deep_agent.
    ex = SandboxedExecutor(FakeOpenShellClient(simulation=True), memo=None, memoize=False)
    b = _bundle()
    with pytest.raises(CapabilityError, match="memoization"):
        ex.execute(b.descriptors[_CAP], {"dossier": {}}, _ctx(b))


def test_deep_agent_memoized_harness_runs_once_on_review_after_resume():
    client = _CountingFakeClient()
    # memoize=False, but deep_agent forces memo (mandatory) since a memo store is present.
    app = _graph(client, memo=InMemoryMemoStore(), memoize=False)
    cfg = {"configurable": {"thread_id": "pi-da-approve"}}

    r = app.invoke(_initial(), cfg)
    # first gate is Task_AssessRepairability (review_after, the deep_agent node)
    p = r["__interrupt__"][0].value
    assert p["element_id"] == "Task_AssessRepairability"
    assert client.calls["Task_AssessRepairability"] == 1

    # approve → resume replays the node; the harness must NOT re-run (mandatory memo).
    r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(p.get("role"))}), cfg)
    while "__interrupt__" in r:
        p2 = r["__interrupt__"][0].value
        r = app.invoke(Command(resume=default_decision(p2)), cfg)
    assert client.calls["Task_AssessRepairability"] == 1, "deep_agent re-ran on resume (memo not mandatory)"
    assert r["outcome"] == "End_Resolved"


def test_deep_agent_reject_reruns_then_approve_does_not():
    client = _CountingFakeClient()
    app = _graph(client, memo=InMemoryMemoStore(), memoize=False)
    cfg = {"configurable": {"thread_id": "pi-da-reject"}}
    r = app.invoke(_initial("EXC-DA-R"), cfg)
    p = r["__interrupt__"][0].value
    assert client.calls["Task_AssessRepairability"] == 1
    # reject → genuine re-run
    r = app.invoke(Command(resume={"decision": "reject", "decided_by": role_user(p.get("role"))}), cfg)
    assert client.calls["Task_AssessRepairability"] == 2
    # approve the re-produced verdict; finish — no further harness runs
    while "__interrupt__" in r:
        p2 = r["__interrupt__"][0].value
        if p2["element_id"] == "Task_AssessRepairability":
            r = app.invoke(Command(resume={"decision": "approve", "decided_by": role_user(p2.get("role"))}), cfg)
        else:
            r = app.invoke(Command(resume=default_decision(p2)), cfg)
    assert client.calls["Task_AssessRepairability"] == 2
    assert r["outcome"] == "End_Resolved"


def test_ac01_runs_to_resolved_through_agentic_pack():
    client = FakeOpenShellClient(simulation=True)
    app = _graph(client, memo=InMemoryMemoStore(), memoize=False)
    cfg = {"configurable": {"thread_id": "pi-da-e2e"}}
    from tests._wire import drive
    result, gates = drive(app, cfg, _initial("EXC-DA-E2E"))
    assert result["outcome"] == "End_Resolved"
    assert result["artifacts"]["beneficiary"]["repair_verdict"] == "repairable"
    # the deep_agent node's capability entry carries a sandbox trace id
    da = [e for e in result["actor_log"] if e["element_id"] == "Task_AssessRepairability"
          and e["kind"] == "capability" and "exec_meta" in e]
    assert da and da[0]["exec_meta"]["via"] == "openshell"
