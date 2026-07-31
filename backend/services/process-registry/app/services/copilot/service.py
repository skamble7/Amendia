# app/services/copilot/service.py
"""The onboarding copilot's generation pipeline (ADR-052 Phase 2a).

One structured LLM call for the semantic leaps, the deterministic engine for the mechanics, deterministic
invariant enforcement on top, then the real 7-stage validator with a bounded repair loop. The output is a
populated session (rendered by the existing technical wizard) plus a ``copilot_report``.

Pipeline: create → attach BPMN (parse + infer) → introspect MCP → semantic call → reconcile + assemble →
repair loop (≤3, re-call the LLM with the exact findings) → persist the session + report. Never hard-fails on
a validation tail — it persists the draft and reports the remainder for the 2b conversation to resolve.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from amendia_bpmn.semantics import extract_semantics

from app.config import settings
from app.services.copilot.flowgraph import build_flow_graph
from app.models.onboarding import (
    AttachBpmnRequest,
    CopilotGenerateRequest,
    CopilotReport,
    CreateSessionRequest,
    IntrospectMcpRequest,
    OnboardingSession,
)
from app.services.copilot.llm import CopilotLLMError, generate_proposal
from app.services.copilot.prompt import build_messages
from app.services.copilot.proposal import CopilotProposal
from app.services.copilot.reconcile import Reconciler
from app.services.copilot.trigger import resolve_trigger_schema
from app.services.onboarding import TransitionError

logger = logging.getLogger(__name__)

_MAX_REPAIR_PASSES = 3


class CopilotService:
    """Wraps an ``OnboardingService`` and drives it through the copilot generation pipeline."""

    def __init__(self, onboarding: Any) -> None:
        self._svc = onboarding

    async def generate(self, req: CopilotGenerateRequest, *, owner: str) -> OnboardingSession:
        # Per-request override → else the service default. Threaded straight into _llm_client(ref); nothing else
        # selects a model. An unknown/unreachable ref surfaces as a clean CopilotLLMError (no silent fallback).
        ref = req.model_config_ref or settings.COPILOT_LLM_CONFIG_REF

        # The trigger is USER-PROVIDED (a JSON Schema or a sample event) — resolve it deterministically up front.
        # A non-object paste is a clean 4xx (user input), not a crash.
        try:
            user_trigger_schema = resolve_trigger_schema(req.trigger)
        except ValueError as exc:
            raise TransitionError(422, {"error": "trigger_invalid", "errors": [{"message": str(exc)}]})

        # 1) create + attach BPMN (parse + inference → session.inferred, the deterministic hint set)
        session = await self._svc.create(CreateSessionRequest(
            pack_key=req.pack_key, version=req.version, title=req.title,
            description=req.description, default_domain=req.domain), owner=owner)
        session = await self._svc.attach_bpmn(session.session_id, AttachBpmnRequest(
            bpmn_xml=req.bpmn_xml, bpmn_file=req.bpmn_file), owner=owner)
        domain = session.basics.default_domain
        process_id = session.bpmn.process_id

        # 2) introspect the MCP server → the tool catalog (non-compliant tools are excluded + reported)
        tools = await self._svc.introspect_mcp(IntrospectMcpRequest(
            endpoint=req.mcp.endpoint, transport=req.mcp.transport, headers=req.mcp.headers, domain=domain))

        # 3) the deterministic semantic model → the grounded prompt (the user trigger schema is passed as ground truth)
        sem = extract_semantics(req.bpmn_xml, process_id)
        base_messages = build_messages(sem=sem, tools=tools, inferred=session.inferred, domain=domain,
                                       trigger_schema=user_trigger_schema)
        trigger_name = _start_event_name(sem)
        # The BPMN flow graph → deterministic loop-back optionality (reconcile marks from='artifact' inputs whose
        # producer isn't a guaranteed upstream predecessor as optional, so a first-pass resolution omits them).
        flow_graph = build_flow_graph(sem)

        # 4) the single semantic call (bindings/dataflow/HITL only — NOT the trigger or triage, which are user-given)
        proposal, model_ref = await generate_proposal(ref=ref, messages=base_messages)

        # 5) reconcile + assemble; 6) bounded repair loop. A proposal-CONTENT rejection (a strict transition 422)
        # must never bubble out of generate — it degrades to a reviewable draft + open question (hard errors are
        # reserved for 502 copilot_llm_unavailable). Deterministic sanitation (reconcile) should prevent this;
        # the wrap is the belt-and-suspenders backstop for any content the engine still refuses.
        try:
            rec, session = await self._reconcile(session, req.mcp, tools, proposal, domain, trigger_name, owner,
                                                 user_trigger_schema=user_trigger_schema,
                                                 user_triage_rules=req.triage_rules, flow_graph=flow_graph)
        except TransitionError as exc:
            return await self._degrade(session, exc, ref, model_ref, owner)
        passes = 0
        while passes < _MAX_REPAIR_PASSES and _has_errors(session):
            passes += 1
            errs = _errors(session)
            logger.info("copilot repair pass %d — %d finding(s)", passes, len(errs))
            try:
                proposal, model_ref = await generate_proposal(
                    ref=ref, messages=base_messages + [_repair_turn(proposal, errs)])
            except CopilotLLMError as exc:
                logger.warning("copilot repair LLM call failed (%s) — keeping the current draft", exc)
                break
            try:
                rec, session = await self._reconcile(session, req.mcp, tools, proposal, domain, trigger_name, owner,
                                                     user_trigger_schema=user_trigger_schema,
                                                     user_triage_rules=req.triage_rules, flow_graph=flow_graph)
            except TransitionError as exc:
                logger.warning("copilot repair reconcile rejected content (%s) — keeping the prior draft", exc.detail)
                break

        # 7) persist the populated session + the report (additive session state)
        report = CopilotReport(
            summary=proposal.summary or "The copilot generated a draft process pack from the diagram and tools.",
            decisions=rec.decisions, open_questions=rec.questions + _residual_questions(session),
            llm_used=True, model_ref=model_ref, repair_passes=passes)
        session.copilot_report = report
        return await self._svc.sessions.save(session)

    async def _degrade(self, session: OnboardingSession, exc: TransitionError, ref: str,
                       model_ref: str, owner: str) -> OnboardingSession:
        """A proposal-content rejection couldn't be reconciled → return a REVIEWABLE degraded draft (not a 4xx/5xx):
        the session in its current state, carrying a report whose open question explains what needs a human."""
        from app.models.onboarding import CopilotOpenQuestion

        current = await self._svc.get(session.session_id, owner=owner)
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        current.copilot_report = CopilotReport(
            summary="The copilot produced a partial draft — one part of the design couldn't be applied "
                    "automatically. Review the open question below, then refine by chat or in the technical detail.",
            decisions=[], llm_used=True, model_ref=model_ref, repair_passes=0,
            open_questions=[CopilotOpenQuestion(
                topic="content", confidence=0.0,
                question=f"I couldn't finish the design automatically: {detail}. Please confirm how this part "
                         f"should work — you can adjust it by chatting or in the technical detail.")])
        logger.warning("copilot generate degraded to a partial draft (%s)", detail)
        return await self._svc.sessions.save(current)

    async def _reconcile(self, session, mcp, tools, proposal: CopilotProposal, domain: str,
                         trigger_name: str, owner: str, *, user_trigger_schema=None,
                         user_triage_rules=None, flow_graph=None) -> Tuple[Reconciler, OnboardingSession]:
        rec = Reconciler(self._svc, domain=domain, mcp=mcp, tools=tools, proposal=proposal,
                         owner=owner, trigger_name=trigger_name,
                         user_trigger_schema=user_trigger_schema, user_triage_rules=user_triage_rules,
                         flow_graph=flow_graph)
        session = await rec.apply(session)
        return rec, session

    # ------------------------------------------------------------------ #
    # ADR-052 Phase 2b — conversational refine
    # ------------------------------------------------------------------ #
    async def chat(self, session_id: str, req: "CopilotChatRequest", *, owner: str) -> "CopilotChatResponse":
        """Interpret one natural-language refine message into typed mutations, apply them through the SAME
        reconcile/validate path (floors enforced), re-validate with the bounded repair loop, update the report +
        conversation log, and reply in plain language with a ChangeDiff. The draft stays activatable each turn."""
        from app.models.onboarding import (
            ChangeDiff, ConversationTurn, CopilotChatResponse, CopilotDecision, CopilotReport)
        from app.services.copilot.llm import interpret_edit
        from app.services.copilot.mutations import (
            apply_mutations, mcp_from_session, open_question_id, proposal_from_session,
            tools_from_session, trigger_name_from_session)
        from app.services.copilot.prompt import build_chat_messages
        from app.services.onboarding import TransitionError

        ref = req.model_config_ref or settings.COPILOT_LLM_CONFIG_REF
        session = await self._svc.get(session_id, owner=owner)
        if not session.bindings:
            raise TransitionError(409, "set bindings (or run the copilot generate) before refining by chat")

        domain = session.basics.default_domain
        proposal = proposal_from_session(session)
        tools = tools_from_session(session)
        mcp = mcp_from_session(session)
        trigger_name = trigger_name_from_session(session)
        report = (session.copilot_report or CopilotReport(llm_used=True)).model_copy(deep=True)
        before = {b.element_id: _snapshot(b) for b in session.bindings}

        conv = [{"message": t.message, "reply": t.reply} for t in session.conversation]
        messages = build_chat_messages(
            proposal_json=proposal.model_dump(by_alias=True), report_json=report.model_dump(),
            open_question_ids=[open_question_id(q) for q in report.open_questions], conversation=conv,
            tool_names=[t.name for t in tools.tools], message=req.message)
        edit, model_ref = await interpret_edit(ref=ref, messages=messages)

        # Clarify, don't guess — apply nothing, session byte-identical, do not persist.
        if edit.needs_clarification or not edit.mutations:
            return CopilotChatResponse(
                reply=edit.reply or "Could you clarify what you'd like to change?", needs_clarification=True,
                changes=[], report=session.copilot_report, validation=session.dry_run_report, session=session)

        edited: set = {m.element_id for m in edit.mutations if m.element_id}
        applied = apply_mutations(proposal, tools, report, edit.mutations)
        rec, session = await self._reconcile(session, mcp, tools, proposal, domain, trigger_name, owner)

        # bounded repair loop — re-call the interpret LLM with the exact findings (as in 2a)
        passes = 0
        while passes < _MAX_REPAIR_PASSES and _has_errors(session):
            passes += 1
            try:
                edit2, _ = await interpret_edit(ref=ref, messages=messages + [_chat_repair_turn(_errors(session))])
            except CopilotLLMError:
                break
            if not edit2.mutations:
                break
            applied += apply_mutations(proposal, tools, report, edit2.mutations)
            edited |= {m.element_id for m in edit2.mutations if m.element_id}
            rec, session = await self._reconcile(session, mcp, tools, proposal, domain, trigger_name, owner)

        # deterministic clamps that fired on the edited elements this turn (reconcile's own record — no 2nd path)
        clamps = [d.summary for d in rec.decisions
                  if d.decided_by == "deterministic" and d.kind == "hitl" and d.element_id in edited]
        changes = _diff(before, session.bindings)
        errs = _errors(session)

        reply = (edit.reply or "Done.").strip()
        if clamps:
            reply += " " + " ".join(clamps)
        if errs:
            reply += (f" Note — the draft still has {len(errs)} validation issue(s) to resolve: "
                      + "; ".join(f"[{e.get('code')}] {e.get('message')}" for e in errs[:3]))

        report.repair_passes = passes
        report.model_ref = model_ref
        report.decisions += [CopilotDecision(kind="chat", decided_by="llm", summary=s) for s in applied]
        report.decisions += [CopilotDecision(kind="hitl", decided_by="deterministic", summary=c) for c in clamps]
        session.copilot_report = report
        session.conversation = list(session.conversation) + [
            ConversationTurn(message=req.message, reply=reply, needs_clarification=False, changes=applied)]
        session = await self._svc.sessions.save(session)
        return CopilotChatResponse(reply=reply, changes=changes, needs_clarification=False,
                                   report=report, validation=session.dry_run_report, session=session)


# --------------------------------------------------------------------------- #
def _start_event_name(sem) -> str:
    start = next((n for n in sem.flow_nodes if n.kind == "startEvent"), None)
    return (start.name if start and start.name else "trigger")


def _findings(session: OnboardingSession) -> List[Dict[str, Any]]:
    report = session.dry_run_report or {}
    return report.get("findings", []) if isinstance(report, dict) else []


def _errors(session: OnboardingSession) -> List[Dict[str, Any]]:
    return [f for f in _findings(session) if f.get("severity") == "error"]


def _has_errors(session: OnboardingSession) -> bool:
    return bool(_errors(session))


def _repair_turn(proposal: CopilotProposal, errors: List[Dict[str, Any]]) -> Dict[str, str]:
    brief = [{"code": e.get("code"), "element_id": e.get("element_id"), "message": e.get("message")}
             for e in errors]
    return {"role": "user", "content": (
        "Your previous proposal produced a draft that FAILED the validator with these errors. Return a "
        "corrected CopilotProposal JSON that fixes ONLY the offending elements; keep everything else.\n"
        f"Previous proposal:\n{json.dumps(proposal.model_dump(by_alias=True), default=str)}\n\n"
        f"Validator errors:\n{json.dumps(brief)}")}


def _residual_questions(session: OnboardingSession):
    from app.models.onboarding import CopilotOpenQuestion
    return [CopilotOpenQuestion(topic="validation", element_id=e.get("element_id"), confidence=0.0,
            question=f"Unresolved after repair: [{e.get('code')}] {e.get('message')}")
            for e in _errors(session)]


# --------------------------------------------------------------------------- #
# chat diff helpers
# --------------------------------------------------------------------------- #
def _snapshot(b) -> Dict[str, Any]:
    """The binding fields a chat edit can move — captured before/after for a ChangeDiff."""
    return {
        "hitl_mode": b.hitl_mode, "hitl_role": b.hitl_role, "capability_ref": b.capability_ref, "role": b.role,
        "output_name": (b.outputs[0].name if b.executor_type == "capability" and b.outputs else None),
        "outputs": [o.name for o in b.outputs], "input_sources": dict(b.input_sources or {}),
        "read_only_inputs": [io.name for io in b.inputs],
    }


def _diff(before: Dict[str, Dict[str, Any]], after_bindings) -> List[Any]:
    from app.models.onboarding import ChangeDiff
    out: List[Any] = []
    for b in after_bindings:
        prev = before.get(b.element_id)
        if prev is None:
            continue
        now = _snapshot(b)
        for field in ("hitl_mode", "hitl_role", "capability_ref", "role", "output_name",
                      "outputs", "input_sources", "read_only_inputs"):
            if prev.get(field) != now.get(field):
                out.append(ChangeDiff(element_id=b.element_id, field=field,
                                      before=prev.get(field), after=now.get(field)))
    return out


def _chat_repair_turn(errors: List[Dict[str, Any]]) -> Dict[str, str]:
    brief = [{"code": e.get("code"), "element_id": e.get("element_id"), "message": e.get("message")}
             for e in errors]
    return {"role": "user", "content": (
        "Applying your edit left the draft with these validator errors. Return a CopilotEdit whose mutations fix "
        "ONLY the offending elements (or needs_clarification if you cannot). Do not undo the operator's intent.\n"
        f"Validator errors:\n{json.dumps(brief)}")}
