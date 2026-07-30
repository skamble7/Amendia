# tests/test_copilot_llm_config.py
"""ADR-052 Phase 2a — the copilot's model selection is fully ConfigForge-driven (no hardcoding).

These exercise the REAL resolution path (``_llm_client`` → ``RemoteConfigLoader.load(ref)``) with a fake
ConfigForge loader + fake LLMClient (no network), proving: the default ref builds the client from the seeded
profile; a per-request ``model_config_ref`` routes to a DIFFERENT profile than the default; and an unresolvable
ref surfaces a clean error naming the ref — never a silent fall-back to some default model.
"""
from __future__ import annotations

import pytest

import polyllm

from app.config import settings
from app.models.onboarding import CopilotGenerateRequest, CopilotMcpConfig
from app.services.copilot import llm as copilot_llm
from app.services.copilot.service import CopilotService
from app.services.onboarding import OnboardingService
from tests._restaurant_copilot import (
    FakeConfigForgeLoader,
    restaurant_bpmn,
    restaurant_proposal_json,
    restaurant_tools,
    restaurant_trigger,
    restaurant_triage,
)
from tests.conftest import FakeMcpIntrospector

OWNER = "usr-owner"
DEFAULT_REF = settings.COPILOT_LLM_CONFIG_REF
ALT_REF = "dev.llm.copilot.alt-profile"


@pytest.fixture
def copilot_svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo):
    svc = OnboardingService(
        onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
        FakeMcpIntrospector(restaurant_tools()), sample_envelopes=[], profile="common_executable")
    return CopilotService(svc)


@pytest.fixture(autouse=True)
def config_forge(monkeypatch):
    """Route _llm_client's lazy ``from polyllm import RemoteConfigLoader`` to the fake, and clear the per-ref
    client cache so each test resolves fresh."""
    copilot_llm._LLM_CLIENTS.clear()
    monkeypatch.setattr(polyllm, "RemoteConfigLoader", FakeConfigForgeLoader)
    monkeypatch.setattr(copilot_llm.settings, "COPILOT_LLM_DISABLED", False)
    yield
    copilot_llm._LLM_CLIENTS.clear()


def _req(**over):
    body = {"pack_key": "rest-stan", "version": "1.0.0", "title": "Restaurant dine-in",
            "bpmn_xml": restaurant_bpmn(), "trigger": restaurant_trigger(), "triage_rules": restaurant_triage(),
            "mcp": CopilotMcpConfig(endpoint="http://dinein-mcp:8070/mcp")}
    body.update(over)
    return CopilotGenerateRequest(**body)


async def test_default_ref_builds_the_client_from_the_seeded_profile(copilot_svc):
    # (a) no per-request override → the SERVICE DEFAULT ref is resolved via ConfigForge and drives the model.
    FakeConfigForgeLoader.reset({DEFAULT_REF: restaurant_proposal_json()})
    session = await copilot_svc.generate(_req(), owner=OWNER)

    assert FakeConfigForgeLoader.LOADED == [DEFAULT_REF]            # resolved exactly the default ref
    assert session.copilot_report.model_ref == DEFAULT_REF
    errors = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errors == [], errors


async def test_per_request_model_config_ref_routes_to_a_different_profile(copilot_svc):
    # (b) a per-request model_config_ref selects a DIFFERENT ConfigForge profile than the default — proving the
    # override routes with no code change. Both refs resolve, but only the OVERRIDE must be used.
    FakeConfigForgeLoader.reset({DEFAULT_REF: restaurant_proposal_json(),
                                 ALT_REF: restaurant_proposal_json()})
    session = await copilot_svc.generate(_req(model_config_ref=ALT_REF), owner=OWNER)

    assert FakeConfigForgeLoader.LOADED == [ALT_REF]               # the override ref, NOT the default
    assert DEFAULT_REF not in FakeConfigForgeLoader.LOADED
    assert session.copilot_report.model_ref == ALT_REF


async def test_unresolvable_ref_is_a_clean_error_not_a_fallback(copilot_svc):
    # (c) an unknown ref → a clean CopilotLLMError naming the ref; the copilot NEVER falls back to the default.
    FakeConfigForgeLoader.reset({DEFAULT_REF: restaurant_proposal_json()})   # default exists, but we ask for a bad ref
    with pytest.raises(copilot_llm.CopilotLLMError) as ei:
        await copilot_svc.generate(_req(model_config_ref="dev.llm.copilot.does-not-exist"), owner=OWNER)

    assert "dev.llm.copilot.does-not-exist" in str(ei.value)       # the ref is in the message
    assert FakeConfigForgeLoader.LOADED == ["dev.llm.copilot.does-not-exist"]  # tried ONLY the bad ref — no fallback


async def test_client_cache_is_keyed_on_the_resolved_ref(copilot_svc):
    # The per-ref cache: two generations on the same ref resolve ConfigForge ONCE (keyed on the ref, not the request).
    FakeConfigForgeLoader.reset({DEFAULT_REF: restaurant_proposal_json()})
    await copilot_svc.generate(_req(), owner=OWNER)
    await copilot_svc.generate(_req(), owner=OWNER)
    assert FakeConfigForgeLoader.LOADED == [DEFAULT_REF]           # resolved once, then served from the cache
    assert DEFAULT_REF in copilot_llm._LLM_CLIENTS
