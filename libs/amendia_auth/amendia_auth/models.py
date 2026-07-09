# amendia_auth/models.py
"""Auth value objects.

``Principal`` is the thin trust boundary with the IdP — only ``iss`` + ``sub``
(plus email/name for display) are ever trusted. ``AuthenticatedUser`` is the
Amendia-side view: the durable ``amendia_user_id`` and the ``role.*`` set that
authorization decisions run against. Vendor role/group claims are never read.
"""
from __future__ import annotations

from typing import Optional, Set

from pydantic import BaseModel, ConfigDict, Field


class Principal(BaseModel):
    """Who the IdP says this is. ``raw_claims`` is kept for debugging only —
    never build authorization logic on it (that is where IdP portability dies)."""

    model_config = ConfigDict(frozen=True)

    iss: str
    sub: str
    email: Optional[str] = None
    name: Optional[str] = None
    raw_claims: dict = Field(default_factory=dict)


class ResolvedUser(BaseModel):
    """The identity service's answer for a principal: the Amendia user + roles.
    Shared wire shape for both the HTTP resolver and identity's local resolver."""

    amendia_user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: str = "active"
    roles: list[str] = Field(default_factory=list)


class AuthenticatedUser(BaseModel):
    """A resolved, authorized caller. ``roles`` is Amendia's ``role.*`` vocabulary;
    ``principal`` is retained so handlers can see the underlying token identity."""

    amendia_user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    roles: Set[str] = Field(default_factory=set)
    principal: Principal

    def has_role(self, role: str) -> bool:
        return role in self.roles
