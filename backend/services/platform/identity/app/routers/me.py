# app/routers/me.py
"""``GET /me`` — the caller's Amendia user + roles (the webui's identity source).

Bearer-authenticated via ``amendia_auth`` itself; the identity service resolves
locally (see ``LocalResolver``) rather than HTTP-calling its own resolve endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from amendia_auth import AuthenticatedUser, current_user

from app.deps import get_user_repo
from app.dal.user_repo import UserRepository
from app.models.identity import UserView

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserView)
async def me(
    user: AuthenticatedUser = Depends(current_user),
    user_repo: UserRepository = Depends(get_user_repo),
):
    stored = await user_repo.get(user.amendia_user_id)
    if stored is None:  # pragma: no cover - resolved user must exist
        raise HTTPException(status_code=404, detail="user not found")
    return UserView(
        amendia_user_id=stored.amendia_user_id,
        identities=stored.identities,
        email=stored.email,
        display_name=stored.display_name,
        status=stored.status.value,
        roles=sorted(user.roles),
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )
