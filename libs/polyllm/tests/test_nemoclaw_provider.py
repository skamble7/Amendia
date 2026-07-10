# libs/polyllm/tests/test_nemoclaw_provider.py
"""Unit tests for the NemoClaw managed-inference provider (ADR-018).

Fully mocked — no network, no real NIM, no langchain_openai dependency: a fake
``langchain_openai`` module is injected so the adapter imports our stub ChatOpenAI.
Covers registry dispatch, chat-model construction (base_url + params), the two credential
modes (host-side resolve vs gateway-brokered), and json_mode fence-stripping.
"""
from __future__ import annotations

import sys
import types

import pytest

from polyllm import LLMClient, PolyllmConfig
from polyllm.config import ModelProfile
from polyllm.providers import get_provider_adapter
from polyllm.providers.nemoclaw import NemoClawAdapter
from polyllm.secrets import default_secret_provider


# --------------------------------------------------------------------------- #
# Fake langchain_openai.ChatOpenAI — records ctor kwargs; returns a canned response.
# --------------------------------------------------------------------------- #
class _FakeAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChatOpenAI:
    last_kwargs: dict = {}
    next_content: str = "{}"

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs
        self.kwargs = kwargs

    async def ainvoke(self, messages):
        return _FakeAIMessage(type(self).next_content)


@pytest.fixture(autouse=True)
def fake_langchain_openai(monkeypatch):
    mod = types.ModuleType("langchain_openai")
    mod.ChatOpenAI = _FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", mod)
    _FakeChatOpenAI.last_kwargs = {}
    _FakeChatOpenAI.next_content = "{}"
    yield


def _profile(**over) -> ModelProfile:
    base = dict(
        provider="nemoclaw",
        model="nemotron-3-ultra",
        base_url="https://inference.local/v1",
        temperature=0.1,
        max_tokens=32000,
        json_mode=True,
    )
    base.update(over)
    return ModelProfile(**base)


# --------------------------------------------------------------------------- #
# Registry dispatch
# --------------------------------------------------------------------------- #
def test_registry_dispatches_nemoclaw():
    adapter = get_provider_adapter("nemoclaw")
    assert isinstance(adapter, NemoClawAdapter)


# --------------------------------------------------------------------------- #
# Chat-model construction
# --------------------------------------------------------------------------- #
def test_adapter_builds_chat_model_with_base_url_and_params():
    adapter = NemoClawAdapter()
    adapter.create_chat_model(
        _profile(), api_key="nim-key-123", credentials={}, secrets=default_secret_provider()
    )
    kw = _FakeChatOpenAI.last_kwargs
    assert kw["base_url"] == "https://inference.local/v1"
    assert kw["model"] == "nemotron-3-ultra"
    assert kw["api_key"] == "nim-key-123"
    assert kw["temperature"] == 0.1
    assert kw["max_tokens"] == 32000


def test_adapter_requires_base_url():
    adapter = NemoClawAdapter()
    with pytest.raises(ValueError, match="base_url"):
        adapter.create_chat_model(
            _profile(base_url=None), api_key="k", credentials={}, secrets=default_secret_provider()
        )


def test_provider_options_passthrough():
    adapter = NemoClawAdapter()
    adapter.create_chat_model(
        _profile(provider_options={"top_p": 0.9}),
        api_key="k", credentials={}, secrets=default_secret_provider(),
    )
    assert _FakeChatOpenAI.last_kwargs["top_p"] == 0.9


# --------------------------------------------------------------------------- #
# Credential modes
# --------------------------------------------------------------------------- #
def test_direct_path_resolves_host_side_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret-xyz")
    cfg = PolyllmConfig(default_profile="d", profiles={"d": _profile(
        provider="nemoclaw", api_key_ref="env:NVIDIA_NIM_API_KEY",
    )})
    client = LLMClient(cfg)
    # chat resolves the key host-side and passes it to the model.
    import anyio
    result = anyio.run(client.chat, [{"role": "user", "content": "hi"}])
    assert _FakeChatOpenAI.last_kwargs["api_key"] == "nim-secret-xyz"
    assert result.raw["provider"] == "nemoclaw"


def test_brokered_path_does_not_demand_host_side_token():
    # No api_key_ref, nothing resolves host-side → the adapter must still build (the gateway
    # injects the scoped token in the in-sandbox path) using a non-secret placeholder.
    adapter = NemoClawAdapter()
    adapter.create_chat_model(
        _profile(), api_key=None, credentials={}, secrets=default_secret_provider()
    )
    assert _FakeChatOpenAI.last_kwargs["api_key"] == "openshell-gateway-brokered"


# --------------------------------------------------------------------------- #
# json_mode — clean JSON out for native and fenced responses
# --------------------------------------------------------------------------- #
def _chat_once(content: str, **profile_over):
    _FakeChatOpenAI.next_content = content
    cfg = PolyllmConfig(default_profile="d", profiles={"d": _profile(**profile_over)})
    import anyio
    return anyio.run(LLMClient(cfg).chat, [{"role": "user", "content": "go"}])


def test_json_mode_native_json_passthrough():
    result = _chat_once('{"verdict": "repairable"}')
    import json
    assert json.loads(result.text) == {"verdict": "repairable"}


def test_json_mode_strips_code_fences():
    result = _chat_once('```json\n{"verdict": "repairable"}\n```')
    import json
    assert json.loads(result.text) == {"verdict": "repairable"}


def test_json_mode_off_leaves_fences(monkeypatch):
    # With json_mode=False no stripping happens (parity with other providers).
    result = _chat_once('```json\n{"x": 1}\n```', json_mode=False)
    assert "```" in result.text


def test_chat_result_carries_provider_and_model():
    result = _chat_once('{}')
    assert result.raw["provider"] == "nemoclaw"
    assert result.raw["model"] == "nemotron-3-ultra"
