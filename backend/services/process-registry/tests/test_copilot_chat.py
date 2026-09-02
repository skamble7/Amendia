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


async def test_set_input_optional_marks_a_loopback_input_absent_tolerant(svc, monkeypatch):
    # ADR-052: the operator can make a not-guaranteed input absent-tolerant conversationally. The flag flows
    # through reconcile (chat path) into the composite source and the draft stays validator-clean.
    session = await _seed(svc, monkeypatch)
    _chat_llm(monkeypatch, _edit(
        "Made the order input on validation absent-tolerant.",
        [{"kind": "set_input_optional", "element_id": "Task_ValidateOrder", "input": "validate_order_input",
          "field": "order", "optional": True, "rationale": "operator says it can be missing on the first pass"}]))

    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="the order can be missing when validation first runs"), owner=OWNER)

    fields = _binding(resp.session, "Task_ValidateOrder").input_sources["validate_order_input"]["fields"]
    assert fields["order"].get("optional") is True
    assert [f for f in (resp.validation or {}).get("findings", []) if f["severity"] == "error"] == []


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


async def test_copilot_chat_preserves_operator_waiver(svc, monkeypatch):
    # ADR-065 Part C / D5: the wizard-waives → copilot-chat-edits → waiver-survives round trip. A chat turn
    # re-runs the whole reconcile; a human's side-effect waiver must never be re-gated or destroyed.
    from amendia_contracts.process_pack import SideEffectWaiver
    session = await _seed(svc, monkeypatch)
    fb = _binding(session, "Task_FireTicket")     # side-effectful, floor-less
    fb.side_effect_waiver = SideEffectWaiver(
        justification="Kitchen fires on the confirmed order; there is no human decision to make here.")
    fb.hitl_mode, fb.hitl_role = "none", None
    await svc.sessions.save(session)

    # a chat turn that edits a DIFFERENT element — the copilot rebuilds every binding under the hood
    _chat_llm(monkeypatch, _edit("route take-order to the manager",
        [{"kind": "set_hitl", "element_id": "Task_TakeOrder", "role": "role.rest_stan.manager", "rationale": "x"}]))
    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="route take-order to the manager"), owner=OWNER)

    fire = _binding(resp.session, "Task_FireTicket")
    assert fire.side_effect_waiver is not None                       # the waiver survived the chat turn
    assert fire.hitl_mode == "none"                                  # NOT re-clamped up to approve_actions
    assert [f for f in (resp.validation or {}).get("findings", []) if f["severity"] == "error"] == []


async def test_copilot_chat_drops_waiver_on_rebind(svc, monkeypatch):
    # ADR-065 P1 follow-up (D1, the blocking hole): a waiver justifies ONE capability. If a chat turn REBINDS the
    # element to a different capability (set_executor), the stale waiver must NOT carry over onto it — it is
    # dropped and the binding re-gated to the side-effect floor, so a high-risk capability can never inherit a
    # justification an operator wrote for a different, low-risk one.
    from amendia_contracts.process_pack import SideEffectWaiver
    session = await _seed(svc, monkeypatch)
    fb = _binding(session, "Task_FireTicket")     # side-effectful (fire_ticket), floor-less, waived at 'none'
    fb.side_effect_waiver = SideEffectWaiver(
        justification="Kitchen fires on the confirmed order; there is no human decision to make here.")
    fb.hitl_mode, fb.hitl_role = "none", None
    await svc.sessions.save(session)

    # rebind Task_FireTicket to a DIFFERENT side-effectful tool (charge_payment)
    _chat_llm(monkeypatch, _edit("actually charge the card at this step",
        [{"kind": "set_executor", "element_id": "Task_FireTicket", "capability_tool": "charge_payment",
          "rationale": "operator changed their mind"}]))
    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="actually charge the card at this step"), owner=OWNER)

    fire = _binding(resp.session, "Task_FireTicket")
    assert fire.capability_ref.split("@", 1)[0] == "cap.rest_stan.charge_payment"   # rebound
    assert fire.side_effect_waiver is None                            # stale waiver DROPPED, not carried over
    assert fire.hitl_mode == "approve_actions"                        # re-gated to the side-effect floor (fail-safe)
    assert any("dropped the operator's side-effect waiver" in d.summary
               for d in resp.report.decisions)                       # the operator is told (decision trace)

    # End-to-end: strip the re-gate (force 'none', no waiver) and assemble — stage 4 now REJECTS the rebound
    # side-effectful capability, proving the stale waiver truly no longer covers charge_payment (hole closed).
    fire.hitl_mode, fire.hitl_role, fire.side_effect_waiver = "none", None, None
    await svc.sessions.save(resp.session)
    s2 = await svc.assemble(resp.session.session_id, owner=OWNER)
    codes2 = {f["code"] for f in (s2.dry_run_report or {}).get("findings", []) if f["severity"] == "error"}
    assert "side_effect_requires_approve_actions" in codes2

    # ...and a FRESH waiver justifying THIS capability clears it again + emits the non-blocking waived warning.
    fire.side_effect_waiver = SideEffectWaiver(
        justification="POS charge is idempotent on the order id; a re-charge is a no-op, nothing to gate here.")
    await svc.sessions.save(resp.session)
    s3 = await svc.assemble(resp.session.session_id, owner=OWNER)
    all3 = {f["code"] for f in (s3.dry_run_report or {}).get("findings", [])}
    assert "side_effect_requires_approve_actions" not in all3
    assert "side_effect_waived" in all3


async def test_copilot_chat_drops_waiver_on_explicit_gate_raise(svc, monkeypatch):
    # ADR-065 P1 follow-up (D1): an operator explicitly asking the copilot to put a STRONGER gate back on a waived
    # binding (set_hitl) must be honoured — the request wins and the waiver is dropped (it would be dead anyway,
    # since a mode at/above the floor leaves nothing to waive). Confirms the premise that the pre-fix branch
    # silently discarded such a set_hitl.
    from amendia_contracts.process_pack import SideEffectWaiver
    session = await _seed(svc, monkeypatch)
    fb = _binding(session, "Task_FireTicket")
    fb.side_effect_waiver = SideEffectWaiver(
        justification="Kitchen fires on the confirmed order; there is no human decision to make here.")
    fb.hitl_mode, fb.hitl_role = "none", None
    await svc.sessions.save(session)

    _chat_llm(monkeypatch, _edit("actually require a manual gate before firing the ticket",
        [{"kind": "set_hitl", "element_id": "Task_FireTicket", "mode": "manual",
          "rationale": "operator wants to authorize each firing"}]))
    resp = await CopilotService(svc).chat(session.session_id, CopilotChatRequest(
        message="actually require a manual gate before firing the ticket"), owner=OWNER)

    fire = _binding(resp.session, "Task_FireTicket")
    assert fire.capability_ref.split("@", 1)[0] == "cap.rest_stan.fire_ticket"      # capability unchanged
    assert fire.side_effect_waiver is None                           # waiver dropped by the deliberate raise
    assert fire.hitl_mode == "manual"                                # the stronger gate the operator asked for wins
    assert any("dropped the operator's side-effect waiver" in d.summary
               for d in resp.report.decisions)
    assert [f for f in (resp.validation or {}).get("findings", []) if f["severity"] == "error"] == []
