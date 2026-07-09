# app/routers/internal.py
"""Internal principal-resolution endpoint, called by ``amendia_auth``'s CurrentUser.

Protected by the shared static internal token (``require_internal``). JIT-provisions
unknown identities. Inside the deployment boundary only.
TODO(auth-hardening): promote to mTLS / signed service tokens (design doc §2.5).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from amendia_auth import require_internal

from app.deps import get_resolve_service
from app.models.identity import ResolvedUserResponse, ResolvePrincipalRequest
from app.services.resolver import ResolveService

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post(
    "/resolve-principal",
    response_model=ResolvedUserResponse,
    dependencies=[Depends(require_internal)],
)
async def resolve_principal(
    body: ResolvePrincipalRequest,
    svc: ResolveService = Depends(get_resolve_service),
):
    resolved = await svc.resolve(iss=body.iss, sub=body.sub, email=body.email, name=body.name)
    return ResolvedUserResponse(**resolved.model_dump())
