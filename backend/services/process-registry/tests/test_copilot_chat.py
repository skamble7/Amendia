# tests/test_copilot_chat.py
"""ADR-052 Phase 2b — the conversational refine endpoint.

Start from the 2a golden restaurant draft, then drive chat turns with a fake LLM returning recorded
``CopilotEdit``s (typed mutations or a clarifying question). Proves: a simple edit applies + re-validates + logs;
a request to drop a required control is CLAMPED to the floor (safety on the chat path too); an ambiguous message
CLARIFIES without touching the draft; an open question resolves; an invalid edit is reported, not fatal; and the
per-request model_config_ref routes through the same ConfigForge seam.
"""
from __future__ import annotations

import json

import pytest

import polyllm

from app.config import settings
from app.models.onboarding import CopilotChatRequest, CopilotGenerateRequest, CopilotMcpConfig
from app.services.copilot import llm as copilot_llm
from app.services.copilot.service import CopilotService
from app.services.onboarding import OnboardingService
from tests._restaurant_copilot import (
    FakeConfigForgeLoader,
    FakeLLMClient,
    restaurant_bpmn,
    restaurant_proposal_json,
    restaurant_tools,
    restaurant_trigger,
    restaurant_triage,
)
from tests.conftest import FakeMcpIntrospector

OWNER = "usr-owner"


@pytest.fixture
def svc(onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo):
    return OnboardingService(
        onboarding_repo, cap_repo, schema_repo, pack_repo, bpmn_repo,
        FakeMcpIntrospector(restaurant_tools()), sample_envelopes=[], profile="common_executable")


def _edit(reply, mutations, needs_clarification=False):
    return json.dumps({"reply": reply, "needs_clarification": needs_clarification, "mutations": mutations})


async def _seed(svc, monkeypatch):
    """Generate the 2a golden restaurant draft (fake LLM → recorded proposal)."""
    monkeypatch.setattr(copilot_llm, "_llm_client", lambda ref: FakeLLMClient([restaurant_proposal_json()]))
    session = await CopilotService(svc).generate(CopilotGenerateRequest(
        pack_key="rest-stan", version="1.0.0", title="Restaurant dine-in", bpmn_xml=restaurant_bpmn(),
        trigger=restaurant_trigger(), triage_rules=restaurant_triage(),
        mcp=CopilotMcpConfig(endpoint="http://dinein-mcp:8070/mcp")), owner=OWNER)
    errs = [f for f in (session.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errs == []
    return session


def _chat_llm(monkeypatch, *edit_jsons):
    monkeypatch.setattr(copilot_llm, "_llm_client", lambda ref: FakeLLMClient(list(edit_jsons)))


def _binding(session, eid):
    return next(b for b in session.bindings if b.element_id == eid)


async def test_simple_edit_applies_revalidates_and_logs(svc, monkeypatch):
    session = await _seed(svc, monkeypatch)
    _chat_llm(monkeypatch, _edit(
        "I moved firing approval to the manager.",
        [{"kind": "set_hitl", "element_id": "Task_FireTicket", "role": "role.rest_stan.manager",
          "rationale": "operator asked the manager to approve firing"}]))

    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="the manager should approve firing the ticket, not the kitchen"), owner=OWNER)

    fire = _binding(resp.session, "Task_FireTicket")
    assert fire.hitl_role == "role.rest_stan.manager"
    assert fire.hitl_mode == "approve_actions"                     # side-effect gate untouched
    assert not resp.needs_clarification
    assert any(c.element_id == "Task_FireTicket" and c.field == "hitl_role" for c in resp.changes)
    assert [f for f in (resp.validation or {}).get("findings", []) if f["severity"] == "error"] == []
    assert resp.session.conversation[-1].message.startswith("the manager should approve")
    assert resp.session.conversation[-1].changes                   # the applied summary was logged


async def test_floor_clamp_on_the_chat_path(svc, monkeypatch):
    # "drop the approval on firing" → fake proposes mode=none; reconcile MUST clamp to approve_actions.
    session = await _seed(svc, monkeypatch)
    _chat_llm(monkeypatch, _edit(
        "Okay, removing the approval on firing.",
        [{"kind": "set_hitl", "element_id": "Task_FireTicket", "mode": "none",
          "rationale": "operator asked to drop the gate"}]))

    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="drop the approval on firing"), owner=OWNER)

    assert _binding(resp.session, "Task_FireTicket").hitl_mode == "approve_actions"    # clamped, not none
    assert "approve_actions" in resp.reply.lower() or "side-effect" in resp.reply.lower()
    assert [f for f in (resp.validation or {}).get("findings", []) if f["severity"] == "error"] == []


async def test_clarify_does_not_guess_and_leaves_the_draft_untouched(svc, monkeypatch):
    session = await _seed(svc, monkeypatch)
    before = (await CopilotService(svc)._svc.get(session.session_id, owner=OWNER)).model_dump(mode="json")
    _chat_llm(monkeypatch, _edit("Which step would you like to make safer?", [], needs_clarification=True))

    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="make it safer"), owner=OWNER)

    assert resp.needs_clarification and resp.changes == []
    after = (await CopilotService(svc)._svc.get(session.session_id, owner=OWNER)).model_dump(mode="json")
    assert after == before                                         # byte-identical — nothing applied, nothing logged


async def test_open_question_resolution_removes_it_from_the_report(svc, monkeypatch):
    from app.services.copilot.mutations import open_question_id
    session = await _seed(svc, monkeypatch)
    # 2a leaves at least one low-confidence open question the operator can answer in the chat.
    oq = session.copilot_report.open_questions
    assert oq, "the seeded draft should carry at least one open question"
    qid = open_question_id(oq[0])
    _chat_llm(monkeypatch, _edit(
        "Confirmed.",
        [{"kind": "resolve_open_question", "question_id": qid,
          "resolution": "confirmed", "rationale": "operator confirmed"}]))

    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="that's correct"), owner=OWNER)

    assert not any(open_question_id(q) == qid for q in resp.report.open_questions)


async def test_invalid_edit_is_reported_not_fatal(svc, monkeypatch):
    # An edit sourcing an input from a non-produced artifact → a validator error. The repair loop runs; the draft
    # persists as a draft with the findings in the reply — not a 500, not a silent success.
    session = await _seed(svc, monkeypatch)
    bad = _edit("Sourcing the order from an external feed.",
                [{"kind": "set_input_map_field", "element_id": "Task_ValidateOrder", "field": "order",
                  "source": {"from": "artifact", "name": "nonexistent_feed"}, "rationale": "operator asked"}])
    giveup = _edit("I can't source that cleanly — please pick an upstream step.", [], needs_clarification=True)
    _chat_llm(monkeypatch, bad, giveup)                            # bad edit, then repair gives up (no mutations)

    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="get the order from an external feed"), owner=OWNER)

    errs = [f for f in (resp.validation or {}).get("findings", []) if f["severity"] == "error"]
    assert errs, "the invalid edit should have produced a validator error"
    assert not resp.needs_clarification
    assert "validation issue" in resp.reply.lower()                # the findings are surfaced in the reply
    # the session persisted as a draft (retrievable), not a crash
    persisted = await CopilotService(svc)._svc.get(session.session_id, owner=OWNER)
    assert persisted.conversation[-1].message.startswith("get the order")


async def test_chat_honors_per_request_model_config_ref(svc, monkeypatch):
    # Same config seam as 2a: the chat call's model_config_ref routes through ConfigForge to a different profile.
    default_ref = settings.COPILOT_LLM_CONFIG_REF
    alt_ref = "dev.llm.copilot.chat-alt"
    edit_json = _edit("Moved firing approval to the manager.",
                      [{"kind": "set_hitl", "element_id": "Task_FireTicket", "role": "role.rest_stan.manager"}])
    FakeConfigForgeLoader.reset({default_ref: restaurant_proposal_json(), alt_ref: edit_json})
    copilot_llm._LLM_CLIENTS.clear()
    monkeypatch.setattr(polyllm, "RemoteConfigLoader", FakeConfigForgeLoader)
    monkeypatch.setattr(copilot_llm.settings, "COPILOT_LLM_DISABLED", False)

    session = await CopilotService(svc).generate(CopilotGenerateRequest(
        pack_key="rest-stan", version="1.0.0", title="R", bpmn_xml=restaurant_bpmn(),
        trigger=restaurant_trigger(), triage_rules=restaurant_triage(),
        mcp=CopilotMcpConfig(endpoint="http://x/mcp")), owner=OWNER)          # resolves the DEFAULT ref
    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="manager approves firing", model_config_ref=alt_ref), owner=OWNER)   # resolves the OVERRIDE ref

    assert FakeConfigForgeLoader.LOADED == [default_ref, alt_ref]
    assert resp.report.model_ref == alt_ref
    assert _binding(resp.session, "Task_FireTicket").hitl_role == "role.rest_stan.manager"
    copilot_llm._LLM_CLIENTS.clear()
