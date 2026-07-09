# app/models/identity.py
"""Identity aggregates + API shapes.

``role`` is validated against the platform ``role.*`` vocabulary (contracts §0).
Only ``iss``/``sub`` are ever stored from a token — never vendor role/group claims.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from amendia_contracts.common import RoleId

# A permissive email shape for staged access — the real check is that the address
# matches (case-insensitively) the one the IdP later asserts at first login.
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Identity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    iss: str
    sub: str


class User(BaseModel):
    """Stored user document (Mongo shape; timestamps are ISO strings)."""

    model_config = ConfigDict(extra="ignore")
    amendia_user_id: str
    identities: List[Identity] = Field(default_factory=list)
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RoleAssignment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amendia_user_id: str
    role: RoleId
    assigned_by: str
    assigned_at: Optional[str] = None


# --------------------------------------------------------------------------- #
# API request/response shapes
# --------------------------------------------------------------------------- #

class ResolvePrincipalRequest(BaseModel):
    iss: str
    sub: str
    email: Optional[str] = None
    name: Optional[str] = None


class ResolvedUserResponse(BaseModel):
    """Matches ``amendia_auth.ResolvedUser`` (the resolver's expected shape)."""

    amendia_user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: str
    roles: List[str] = Field(default_factory=list)


class RoleAssignmentView(BaseModel):
    """Per-role grant metadata for the admin user-detail screen."""

    role: str
    assigned_by: Optional[str] = None
    assigned_at: Optional[str] = None


class UserView(BaseModel):
    amendia_user_id: str
    identities: List[Identity]
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: str
    roles: List[str] = Field(default_factory=list)
    # Only populated by the admin endpoints (not /me): the who/when behind each role.
    role_details: List[RoleAssignmentView] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AssignRoleRequest(BaseModel):
    role: RoleId


# --------------------------------------------------------------------------- #
# Pending (staged) role assignments — attached by email at first JIT login
# --------------------------------------------------------------------------- #

class PendingView(BaseModel):
    """Aggregated staged access for one email (one row per role underneath)."""

    email: str
    roles: List[str] = Field(default_factory=list)
    staged_by: Optional[str] = None
    staged_at: Optional[str] = None


class StagePendingRequest(BaseModel):
    """Stage access for an email that hasn't signed in yet. ``roles`` are each
    validated against the ``role.*`` vocabulary (422 on a bad pattern)."""

    email: str = Field(pattern=EMAIL_RE)
    roles: List[RoleId] = Field(min_length=1)


class ReplacePendingRequest(BaseModel):
    """Replace the full set of staged roles for an already-staged email."""

    roles: List[RoleId] = Field(min_length=1)
