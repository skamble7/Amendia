# tests/test_nemoclaw_provider_routing.py
"""ADR-018 Part D — a `nemoclaw` ref routes `llm` capabilities to the NemoClaw provider,
through the SAME `run_real_llm` seam in BOTH `native` and `nemoclaw`(fake) execution modes.

Fully mocked: a fake `langchain_openai` module + a patched `_llm_client` mean no ConfigForge,
no network, no NIM. Agent-runtime code is NOT modified — this only exercises it. Proves the
ref plumbing ADR-017 threaded (Part F) makes the new provider usable with zero executor
change.
"""
from __future__ import annotations

import json
import sys
import types

import pytest
from jsonschema import Draft202012Validator

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.executor import InProcessExecutor, SandboxedExecutor
from app.engine.executor import dispatch
from app.engine.executor.base import ExecutionContext
from app.engine.executor.openshell import FakeOpenShellClient
from app.capabilities.wire_repair import draft_repair
from tests._wire import make_envelope

NEMO_REF = "dev.llm.nemoclaw.nemotron-ultra"
_ARTIFACT = "art.payment.repair_instruction"


# --------------------------------------------------------------------------- #
class _FakeAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChatOpenAI:
    """Records ctor kwargs; returns a canned, schema-valid repair_instruction JSON."""
    last_kwargs: dict = {}
    canned: str = "{}"

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs

    async def ainvoke(self, messages):
        return _FakeAIMessage(type(self).canned)


@pytest.fixture
def bundle() -> PackBundle:
    return PackBundle.from_seed_dir(settings.SEED_DIR)


@pytest.fixture(autouse=True)
def nemoclaw_wired(monkeypatch, bundle):
    """Inject a fake langchain_openai and route `_llm_client(ref)` to a real polyllm
    LLMClient built on a `nemoclaw` ModelProfile — capturing every ref passed."""
    from polyllm import LLMClient, PolyllmConfig
    from polyllm.config import ModelProfile

    mod = types.ModuleType("langchain_openai")
    mod.ChatOpenAI = _FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", mod)

    # Canned artifact = the sim capability's own (guaranteed schema-valid) output.
    valid = draft_repair.run(inputs={"beneficiary": {}}, envelope=make_envelope("AC01"))
    _FakeChatOpenAI.canned = json.dumps(valid["outputs"][_ARTIFACT])

    nemo_client = LLMClient(PolyllmConfig(default_profile="default", profiles={"default": ModelProfile(
        provider="nemoclaw", model="nemotron-3-ultra",
        base_url="https://inference.local/v1", json_mode=True,
    )}))

    seen_refs: list[str] = []

    def fake_llm_client(ref):
        seen_refs.append(ref)
        return nemo_client

    monkeypatch.setattr(dispatch, "_llm_client", fake_llm_client)
    # Clear the module cache so our patch is always consulted.
    monkeypatch.setattr(dispatch, "_LLM_CLIENTS", {})
    return seen_refs


def _ctx(bundle):
    schema = bundle.schemas[f"{_ARTIFACT}@1.0.0"]
    return ExecutionContext(
        envelope=make_envelope("AC01"), mode="execute", simulation=False,
        extras={"output_schemas": {_ARTIFACT: schema}, "element_id": "Task_DraftRepair"},
    )


def _assert_valid(bundle, produced):
    schema = bundle.schemas[f"{_ARTIFACT}@1.0.0"]
    assert not list(Draft202012Validator(schema).iter_errors(produced[_ARTIFACT]))


# --------------------------------------------------------------------------- #
def test_native_routes_defaulting_llm_capability_to_nemoclaw(monkeypatch, bundle, nemoclaw_wired):
    monkeypatch.setattr(settings, "LLM_CONFIG_REF", NEMO_REF)
    descriptor = bundle.descriptors["cap.payment.draft_repair"]  # no model_config_key → default

    out = InProcessExecutor().execute(descriptor, {"beneficiary": {}}, _ctx(bundle))

    assert nemoclaw_wired == [NEMO_REF]              # the default ref flowed through
    assert "(nemoclaw:" in out["log"]                # routed to the nemoclaw provider
    _assert_valid(bundle, out["outputs"])            # schema-valid artifact


def test_nemoclaw_fake_mode_routes_to_nemoclaw(monkeypatch, bundle, nemoclaw_wired):
    monkeypatch.setattr(settings, "LLM_CONFIG_REF", NEMO_REF)
    descriptor = bundle.descriptors["cap.payment.draft_repair"]
    ex = SandboxedExecutor(FakeOpenShellClient(simulation=False), fallback=InProcessExecutor())

    out = ex.execute(descriptor, {"beneficiary": {}}, _ctx(bundle))

    assert nemoclaw_wired == [NEMO_REF]
    assert out["exec_meta"]["provider"] == "nemoclaw"
    assert "via OpenShell sandbox trace=" in out["log"]
    _assert_valid(bundle, out["outputs"])


def test_per_capability_model_config_key_routes_single_capability(monkeypatch, bundle, nemoclaw_wired):
    # Platform default stays on Bedrock; only this capability overrides to a nemoclaw ref.
    monkeypatch.setattr(settings, "LLM_CONFIG_REF", "dev.llm.bedrock.explicit-creds")
    per_cap_ref = "dev.llm.nemoclaw.nim"
    descriptor = bundle.descriptors["cap.payment.draft_repair"].model_copy(deep=True)
    descriptor.runtime.model_config_key = per_cap_ref

    InProcessExecutor().execute(descriptor, {"beneficiary": {}}, _ctx(bundle))

    # The capability's own declaration wins over the platform default (ADR-016 rule).
    assert nemoclaw_wired == [per_cap_ref]
