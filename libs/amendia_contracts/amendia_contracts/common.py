# amendia_contracts/common.py
"""Shared value types for the platform contracts.

Everything here is common to more than one contract: the ``VersionedRef`` value
object (`<id>@<range-or-pin>`), the closed ``HitlMode`` set, regex-backed id/pattern
string types, a stored-document timestamp mixin, and the event ``EventBase`` that
delegates routing-key construction to ``amendia_common.events.rk``.

Source of truth: ``backend/docs/amendia_platform_contracts_v1.md`` (§0 conventions).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from amendia_common.events import Version, rk
from amendia_contracts.semver import satisfies

# --------------------------------------------------------------------------- #
# Regex patterns (single source, reused by the string types below)
# --------------------------------------------------------------------------- #

SEMVER_RE = r"^\d+\.\d+\.\d+$"
PACK_KEY_RE = r"^[a-z][a-z0-9-]*$"
CAP_ID_RE = r"^cap\.[a-z0-9_]+\.[a-z0-9_]+$"
ART_ID_RE = r"^art\.[a-z0-9_]+\.[a-z0-9_]+$"
ROLE_ID_RE = r"^role\.[a-z0-9_.]+$"
ART_PREFIX_RE = r"^art\."
SHA256_RE = r"^[a-f0-9]{64}$"

# Annotated string types with pattern enforcement.
SemVerStr = Annotated[str, StringConstraints(pattern=SEMVER_RE)]
PackKey = Annotated[str, StringConstraints(pattern=PACK_KEY_RE)]
CapabilityId = Annotated[str, StringConstraints(pattern=CAP_ID_RE)]
ArtifactKey = Annotated[str, StringConstraints(pattern=ART_ID_RE)]
RoleId = Annotated[str, StringConstraints(pattern=ROLE_ID_RE)]
ArtifactBareRef = Annotated[str, StringConstraints(pattern=ART_PREFIX_RE)]
Sha256Hex = Annotated[str, StringConstraints(pattern=SHA256_RE)]

_PINNED_RE = re.compile(SEMVER_RE)


# --------------------------------------------------------------------------- #
# HITL modes (contracts 1, 2, 5)
# --------------------------------------------------------------------------- #

class HitlMode(str, Enum):
    NONE = "none"
    REVIEW_AFTER = "review_after"
    APPROVE_RESULT = "approve_result"
    APPROVE_ACTIONS = "approve_actions"
    MANUAL = "manual"


# Strictness ranking for policy checks: none < review_after <= approve_result
# < approve_actions ~= manual  (contracts doc §0 / reference §2.4).
_HITL_RANK = {
    HitlMode.NONE: 0,
    HitlMode.REVIEW_AFTER: 1,
    HitlMode.APPROVE_RESULT: 1,
    HitlMode.APPROVE_ACTIONS: 2,
    HitlMode.MANUAL: 2,
}


def hitl_rank(mode: HitlMode | str) -> int:
    return _HITL_RANK[HitlMode(mode)]


def hitl_mode_at_least(mode: HitlMode | str, floor: HitlMode | str) -> bool:
    """True if ``mode`` is at least as strict as ``floor`` under the documented ordering.

    Used for the two policy checks: a capability's ``min_hitl_mode`` is a floor a binding
    may tighten but never loosen, and ``side_effectful`` capabilities require
    ``approve_actions`` or stricter.
    """
    return hitl_rank(mode) >= hitl_rank(floor)


# --------------------------------------------------------------------------- #
# VersionedRef — `<id>@<range-or-pin>`
# --------------------------------------------------------------------------- #

class VersionedRef:
    """A reference to a versioned entity, e.g. ``cap.payment.draft_repair@^1.0.0``.

    Parses into ``ref_id`` (the dotted id) and ``spec`` (the version range or pin).
    Serializes back to the compact ``<id>@<spec>`` string. Subclasses fix the
    required prefix (``cap`` / ``art``) so the reference is validated by context.
    """

    prefix: ClassVar[Optional[str]] = None  # e.g. "cap" / "art"; None = any

    __slots__ = ("ref_id", "spec")

    def __init__(self, ref_id: str, spec: str) -> None:
        self.ref_id = ref_id
        self.spec = spec

    @property
    def is_pinned(self) -> bool:
        """True when ``spec`` is an exact semver pin (not a range)."""
        return bool(_PINNED_RE.match(self.spec))

    def matches(self, exact_version: str) -> bool:
        """True if an exact registered version satisfies this ref's range/pin."""
        return satisfies(exact_version, self.spec)

    def __str__(self) -> str:
        return f"{self.ref_id}@{self.spec}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self!s})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VersionedRef):
            return self.ref_id == other.ref_id and self.spec == other.spec
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.ref_id, self.spec))

    @classmethod
    def parse(cls, raw: str) -> "VersionedRef":
        if not isinstance(raw, str):
            raise TypeError(f"VersionedRef must be a string, got {type(raw).__name__}")
        if raw.count("@") != 1:
            raise ValueError(f"invalid versioned ref '{raw}': expected exactly one '@'")
        ref_id, spec = raw.split("@", 1)
        if not ref_id or not spec:
            raise ValueError(f"invalid versioned ref '{raw}': empty id or spec")
        if not re.match(r"^[a-z][a-z0-9_.]*$", ref_id):
            raise ValueError(f"invalid ref id '{ref_id}': must be lowercase dotted")
        if cls.prefix is not None and not ref_id.startswith(cls.prefix + "."):
            raise ValueError(f"ref '{ref_id}' must start with '{cls.prefix}.'")
        return cls(ref_id, spec)

    # -- Pydantic integration: validate from str (or pass-through instances),
    #    serialize to the compact str, present as a string in JSON schema. --
    @classmethod
    def _validate(cls, value: object) -> "VersionedRef":
        if isinstance(value, VersionedRef):
            return cls.parse(str(value))
        return cls.parse(value)  # type: ignore[arg-type]

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler: GetCoreSchemaHandler):
        from_str = core_schema.no_info_plain_validator_function(cls._validate)
        return core_schema.json_or_python_schema(
            json_schema=from_str,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_str]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, when_used="always"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, _handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # The wire form is always the compact `<id>@<range-or-pin>` string, so
        # present it as a plain string in JSON Schema / OpenAPI. (Delegating to
        # the handler would fail: the core schema is a plain validator function
        # with no JSON representation.)
        prefix = f"{cls.prefix}." if cls.prefix else ""
        return {
            "type": "string",
            "title": cls.__name__,
            "description": "Versioned reference '<id>@<range-or-pin>'.",
            "examples": [f"{prefix}payment.draft_repair@^1.0.0" if cls.prefix else "cap.payment.draft_repair@1.0.0"],
        }


class CapabilityRef(VersionedRef):
    prefix = "cap"


class ArtifactRef(VersionedRef):
    prefix = "art"


# --------------------------------------------------------------------------- #
# Base models
# --------------------------------------------------------------------------- #

class ContractModel(BaseModel):
    """Base for every contract model: forbid unknown fields (mirrors
    ``additionalProperties: false``), allow population by field name as well as
    alias (so `schema`/`not` aliases round-trip), and disable protected
    namespaces so fields like ``model_config_key`` are allowed."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        protected_namespaces=(),
    )

    def to_doc(self) -> dict:
        """JSON-mode dump using aliases — the exact shape persisted in Mongo."""
        return self.model_dump(mode="json", by_alias=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampsMixin(BaseModel):
    """Store-managed timestamps added to persisted contract documents."""

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# --------------------------------------------------------------------------- #
# Event base (contracts 4 + thin HITL events)
# --------------------------------------------------------------------------- #

class EventBase(ContractModel):
    """Shared envelope for events published on ``amendia.events``."""

    # Subclasses set these to build the routing key via amendia_common.events.rk.
    _service: ClassVar[object]
    _event_name: ClassVar[str]

    event_id: str
    occurred_at: datetime
    schema_version: str
    tenant: str

    def routing_key(self, tenant: Optional[str] = None) -> str:
        """`<tenant>.<service>.<event>.v1` via the shared rk() builder."""
        return rk(tenant or self.tenant, self._service, self._event_name, Version.V1.value)
