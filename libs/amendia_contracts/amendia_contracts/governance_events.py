# amendia_contracts/governance_events.py
"""ADR-058 Phase B — governed decision-point events.

These are the domain events emitted at governance/audit-relevant decision points that had no event
before: egress allow/deny, artifact commit, identity role grant/revoke, pack lifecycle, and config-ref
resolution. ``glea-service`` consumes them off the ``amendia.events`` exchange and persists them into the
append-only ``audit_events`` system-of-record. Every field is **structural / domain-neutral** — no pack
or business term ever enters an event field or routing key (a review gate).

Each event carries a :class:`Trace` (``correlation_id`` + the OTel ``trace_id``) so an audit row joins to
its Phase-A ``otel_traces`` spans. Follows the existing ``EventBase`` shape (``event_id``/``occurred_at``/
``schema_version``; ``routing_key()`` via ``amendia_common.events.rk``).
"""
from __future__ import annotations

from enum import Enum
from typing import ClassVar, Literal, Optional

from amendia_common.events import (
    ARTIFACT_COMMITTED,
    CONFIG_REF_RESOLVED,
    EGRESS_DECISION,
    PACK_LIFECYCLE,
    ROLE_CHANGED,
    Service,
)
from amendia_contracts.common import EventBase, RoleId, SemVerStr
from amendia_contracts.dispatch import Trace


class EgressDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class RoleChangeOp(str, Enum):
    GRANT = "grant"
    REVOKE = "revoke"


class PackLifecycleOp(str, Enum):
    PUBLISH = "publish"
    DEPRECATE = "deprecate"
    ROLLBACK = "rollback"
    DELETE = "delete"                              # ADR-061: force-delete a pack version / whole pack (audit-first)


# --------------------------------------------------------------------------- #
# agent-runtime governed points
# --------------------------------------------------------------------------- #
class EgressDecisionEvent(EventBase):
    """A capability's outbound-host access was allowed or denied against its derived egress allowlist
    (ADR-019). Emitted on ``deny`` always; ``allow`` may be sampled to bound volume."""

    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = EGRESS_DECISION

    schema_version: Literal["pin.platform.egress_decision/1.0"] = "pin.platform.egress_decision/1.0"
    process_instance_id: str
    element_id: str
    capability_id: str
    execution_mode: str          # native | nemoclaw
    host: str                    # the target host that was allowed/denied
    decision: EgressDecision
    enforced: bool = False       # True → the call was blocked (NATIVE_EGRESS_ENFORCE); False → audit-only
    trace: Trace


class ArtifactCommittedEvent(EventBase):
    """A validated artifact was committed by a node — the lineage/audit record of a produced output
    (its pinned ``schema_ref`` and whether a human authored it)."""

    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = ARTIFACT_COMMITTED

    schema_version: Literal["pin.platform.artifact_committed/1.0"] = "pin.platform.artifact_committed/1.0"
    process_instance_id: str
    element_id: str
    artifact_key: str
    schema_ref: str
    actor: str
    actor_kind: str              # capability | human | call
    authored_by_human: Optional[bool] = None
    # ADR-058 Phase C: the reasoning capability's bounded rationale, when it produced one (deep-agent/
    # LLM). Absent for a plain MCP tool (no reasoning — never fabricated). Structural key; content value.
    rationale: Optional[str] = None
    trace: Trace


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
class RoleChangedEvent(EventBase):
    """A role grant/revoke on identity — including a refused outcome (self-/last-admin protection), so
    the audit trail records attempts, not only successes."""

    _service: ClassVar[Service] = Service.IDENTITY
    _event_name: ClassVar[str] = ROLE_CHANGED

    schema_version: Literal["pin.platform.role_changed/1.0"] = "pin.platform.role_changed/1.0"
    subject_user: str            # the user whose roles changed
    role: RoleId
    op: RoleChangeOp
    actor: str                   # the admin performing the change
    outcome: str                 # granted | revoked | self_protection | last_admin | duplicate | ...
    trace: Optional[Trace] = None


# --------------------------------------------------------------------------- #
# process-registry
# --------------------------------------------------------------------------- #
class PackLifecycleEvent(EventBase):
    """A pack version transitioned lifecycle state (publish/activate, deprecate, rollback)."""

    _service: ClassVar[Service] = Service.PROCESS_REGISTRY
    _event_name: ClassVar[str] = PACK_LIFECYCLE

    schema_version: Literal["pin.platform.pack_lifecycle/1.0"] = "pin.platform.pack_lifecycle/1.0"
    pack_key: str
    version: SemVerStr
    op: PackLifecycleOp
    actor: str
    detail: Optional[str] = None
    trace: Optional[Trace] = None


# --------------------------------------------------------------------------- #
# config-forge
# --------------------------------------------------------------------------- #
class ConfigRefResolvedEvent(EventBase):
    """A config/credential reference was resolved (which ref, by whom, resolved-or-not) — structural
    only; the resolved VALUE never enters the event."""

    _service: ClassVar[Service] = Service.CONFIG_FORGE
    _event_name: ClassVar[str] = CONFIG_REF_RESOLVED

    schema_version: Literal["pin.platform.config_ref_resolved/1.0"] = "pin.platform.config_ref_resolved/1.0"
    ref: str
    resolved: bool
    actor: Optional[str] = None
    trace: Optional[Trace] = None
