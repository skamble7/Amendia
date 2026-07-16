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

from app.deps import get_onboarding_service
from app.models.onboarding import (
    AttachBpmnRequest,
    CreateSessionRequest,
    IntrospectMcpRequest,
    IntrospectMcpResponse,
    OnboardingSession,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    SetTriageRequest,
)
from app.services.onboarding import OnboardingService, TransitionError

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
# The introspection endpoint sits under /capabilities to match the catalog it feeds.
introspect_router = APIRouter(prefix="/capabilities", tags=["onboarding"])

_owner_user = require_roles("role.process.owner")


def _owner_id(user: AuthenticatedUser = Depends(_owner_user)) -> str:
    return user.amendia_user_id


def _raise(exc: TransitionError):
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
):
    try:
        return await svc.commit(session_id, owner=owner)
    except TransitionError as exc:
        _raise(exc)
