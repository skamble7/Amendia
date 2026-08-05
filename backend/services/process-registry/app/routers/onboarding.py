# app/routers/onboarding.py
"""Form-driven onboarding: the OnboardingSession state machine over HTTP.

Every mutation is process-owner gated; sessions are owner-scoped. Each transition returns
the full updated session so the webui can render it (thin renderer). ``TransitionError`` from
the service carries the HTTP status + a field-level detail body.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from amendia_auth import require_roles
from amendia_auth.models import AuthenticatedUser

from app.deps import get_onboarding_service, get_resolver
from app.models.onboarding import (
    AttachBpmnRequest,
    CopilotChatRequest,
    CopilotChatResponse,
    CopilotGenerateRequest,
    CreateSessionRequest,
    EditPackRequest,
    DeclareArtifactRequest,
    RefineArtifactRequest,
    DeclareTriggerRequest,
    IntrospectMcpRequest,
    IntrospectMcpResponse,
    OnboardingSession,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
)
from app.services.copilot.llm import CopilotLLMError
from app.services.copilot.service import CopilotService
from app.services.onboarding import OnboardingService, TransitionError

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
# The introspection endpoint sits under /capabilities to match the catalog it feeds.
introspect_router = APIRouter(prefix="/capabilities", tags=["onboarding"])

_owner_user = require_roles("role.process.owner")


def _owner_id(user: AuthenticatedUser = Depends(_owner_user)) -> str:
    return user.amendia_user_id


import logging as _logging

_tlog = _logging.getLogger("app.onboarding.transition")


def _raise(exc: TransitionError):
    # Diagnostic: log the field-level detail body (e.g. bindings_invalid -> which element/field)
    # so a 4xx transition is visible in the service log tail, not just the HTTP status code.
    _tlog.warning("onboarding transition rejected: status=%s detail=%s", exc.status_code, exc.detail)
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --------------------------------------------------------------------------- #
# MCP introspection (no session)
# --------------------------------------------------------------------------- #

@introspect_router.post("/introspect-mcp", response_model=IntrospectMcpResponse)
async def introspect_mcp(
    req: IntrospectMcpRequest,
    _owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.introspect_mcp(req)
    except TransitionError as exc:
        _raise(exc)


# --------------------------------------------------------------------------- #
# ADR-052 Phase 2a — the onboarding copilot (autopilot generation)
# --------------------------------------------------------------------------- #

@router.post("/copilot/generate", response_model=OnboardingSession, status_code=201)
async def copilot_generate(
    req: CopilotGenerateRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    """Given a comprehensive BPMN + a live MCP endpoint, generate a complete, validator-clean DRAFT pack into a
    new onboarding session (deterministic engine + one LLM call + deterministic invariant enforcement + the
    7-stage validator with a bounded repair loop). Returns the populated session — reviewable/activatable in the
    existing wizard — carrying its ``copilot_report`` (plain-language summary + provenance + open questions)."""
    try:
        return await CopilotService(svc).generate(req, owner=owner)
    except TransitionError as exc:
        _raise(exc)
    except CopilotLLMError as exc:
        raise HTTPException(status_code=502, detail={"error": "copilot_llm_unavailable", "message": str(exc)})


@router.post("/{session_id}/copilot/chat", response_model=CopilotChatResponse)
async def copilot_chat(
    session_id: str,
    req: CopilotChatRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    """ADR-052 Phase 2b — conversational refine. Interpret one natural-language edit into typed mutations, apply
    them through the same deterministic reconcile/validate path (floors always enforced), re-validate, update the
    copilot_report + conversation log, and reply in plain language with a ChangeDiff. The draft stays activatable."""
    try:
        return await CopilotService(svc).chat(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)
    except CopilotLLMError as exc:
        raise HTTPException(status_code=502, detail={"error": "copilot_llm_unavailable", "message": str(exc)})


# --------------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------------- #

@router.post("", response_model=OnboardingSession, status_code=201)
async def create_session(
    req: CreateSessionRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.create(req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.post("/from-pack/{pack_key}", response_model=OnboardingSession, status_code=201)
async def edit_pack(
    pack_key: str, req: EditPackRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    """ADR-056: open an EDIT session over an activated pack — hydrate its config into a bumped-version onboarding
    session, editable through the stepped review; committing publishes the new version (auto-deprecating the prior)."""
    try:
        return await svc.create_edit_session(pack_key, bump=req.bump, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.get("", response_model=List[OnboardingSession])
async def list_sessions(
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    return await svc.list(owner=owner)


@router.get("/{session_id}", response_model=OnboardingSession)
async def get_session(
    session_id: str,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.get(session_id, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        await svc.delete(session_id, owner=owner)
    except TransitionError as exc:
        _raise(exc)


# --------------------------------------------------------------------------- #
# Transitions
# --------------------------------------------------------------------------- #

@router.put("/{session_id}/bpmn", response_model=OnboardingSession)
async def attach_bpmn(
    session_id: str, req: AttachBpmnRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.attach_bpmn(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.post("/{session_id}/capabilities", response_model=OnboardingSession)
async def set_capabilities(
    session_id: str, req: SetCapabilitiesRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.set_capabilities(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.put("/{session_id}/bindings", response_model=OnboardingSession)
async def set_bindings(
    session_id: str, req: SetBindingsRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.set_bindings(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.put("/{session_id}/trigger", response_model=OnboardingSession)
async def declare_trigger(
    session_id: str, req: DeclareTriggerRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    """ADR-049: declare the pack's trigger artifact schema (drives the Triage field picker)."""
    try:
        return await svc.declare_trigger(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.put("/{session_id}/artifacts", response_model=OnboardingSession)
async def declare_artifact(
    session_id: str, req: DeclareArtifactRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    """ADR-050: declare (upsert) an operator-authored artifact schema — one a human/message binding can
    output (e.g. art.dining.order). Registered + listed among the pack artifacts at assemble."""
    try:
        return await svc.declare_artifact(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.put("/{session_id}/artifacts/refine", response_model=OnboardingSession)
async def refine_artifact(
    session_id: str, req: RefineArtifactRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    """ADR-054: refine a human-authored artifact's JSON schema (typed props, labels, enums). The version is
    resolved server-side (bump-on-change) and the referencing bindings are re-pinned, so the activated pack's
    HITL form renders labeled, typed fields — not a raw JSON blob."""
    try:
        return await svc.refine_artifact(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.put("/{session_id}/triage", response_model=OnboardingSession)
async def set_triage(
    session_id: str, req: SetTriageRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.set_triage(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.put("/{session_id}/policies", response_model=OnboardingSession)
async def set_policies(
    session_id: str, req: SetPoliciesRequest,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.set_policies(session_id, req, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.post("/{session_id}/assemble", response_model=OnboardingSession)
async def assemble(
    session_id: str,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
):
    try:
        return await svc.assemble(session_id, owner=owner)
    except TransitionError as exc:
        _raise(exc)


@router.post("/{session_id}/commit", response_model=OnboardingSession)
async def commit(
    session_id: str,
    owner: str = Depends(_owner_id),
    svc: OnboardingService = Depends(get_onboarding_service),
    resolver=Depends(get_resolver),
):
    try:
        session = await svc.commit(session_id, owner=owner)
    except TransitionError as exc:
        _raise(exc)
    # ADR-056: commit may have activated a new version + auto-deprecated a prior one — drop the resolver's
    # active-pack cache so NEW events route to the just-published version immediately.
    resolver.invalidate()
    return session
