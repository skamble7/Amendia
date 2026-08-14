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
    COHORT_LIFECYCLE,
    COHORT_SLA,
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


class CohortLifecycleOp(str, Enum):
    """ADR-063 cohort-instance state/roster transitions (purely observational)."""
    OPENED = "opened"                # first member spawned → cohort instance created
    MEMBER_JOINED = "member_joined"  # a segment instance joined the cohort's roster
    CLOSING = "closing"              # external close signal arrived while ≥1 member still running (Phase 2)
    CLOSED = "closed"                # cohort terminal — no member in flight (Phase 2)
    LATE_JOIN = "late_join"          # anomaly: joined a closed cohort, or a cohort_def_id-mismatch member


class CohortSlaState(str, Enum):
    """ADR-064 P2 — the state a cohort SLA expectation is emitted in (a subset of the persisted state
    machine ``pending | at_risk | satisfied | voided | breached``; ``pending`` is never emitted)."""
    AT_RISK = "at_risk"      # crossed the at-risk lead with the satisfying event still outstanding (amber)
    BREACHED = "breached"    # crossed the deadline unmet — recorded + attributed to an owner
    SATISFIED = "satisfied"  # the satisfying event arrived in time (optional; useful for P3 rollups)
    VOIDED = "voided"        # excused — XOR sibling arrived, or the cohort closed (never a fault)


class CohortSlaKind(str, Enum):
    """Which expectation a cohort SLA measures (structural — mirrors the ADR-064 graph shapes)."""
    EDGE = "edge"              # a precedence hop (after anchor of `from`, expect `to`)
    NODE = "node"             # a segment's own arrival → completion runtime promise
    END_TO_END = "end_to_end" # the whole case (cohort open → close)


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


class CohortLifecycleEvent(EventBase):
    """ADR-063 Phase 1 — a cohort instance's own lifecycle/roster transition, emitted fail-soft by
    agent-runtime (mirrors ``PackLifecycleEvent``). Thin on purpose: it carries only the cohort's OWN
    transitions and never re-emits member terminal outcomes (member instances publish their own terminal
    telemetry — one source of truth). Fields stay structural/domain-neutral: ``correlation_value`` is opaque
    data, never a business-term key. Per-op detail: ``process_instance_id``/``pack_key`` on ``member_joined``/
    ``late_join``; a short ``detail`` anomaly string on ``late_join``."""

    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = COHORT_LIFECYCLE

    schema_version: Literal["pin.platform.cohort_lifecycle/1.0"] = "pin.platform.cohort_lifecycle/1.0"
    cohort_def_id: str
    cohort_instance_id: str
    correlation_value: str                          # opaque business key (structural — not a domain term)
    op: CohortLifecycleOp
    process_instance_id: Optional[str] = None       # the joining member (member_joined / late_join)
    pack_key: Optional[str] = None                  # the joining member's pack (member_joined / late_join)
    # ADR-063 Phase 3A: the joining member's pinned pack version (member_joined / late_join) — the roster read-
    # model needs it to fetch the right BPMN. Set alongside pack_key.
    pack_version: Optional[str] = None
    # ADR-063 Phase 3A: the orchestrator-reported overall outcome (closing / closed) as a first-class field, so
    # the read-model reads a clean column instead of parsing it out of `detail` (which is still set too).
    close_outcome: Optional[str] = None
    detail: Optional[str] = None                    # anomaly / close-outcome note (late_join, closing, closed)
    trace: Optional[Trace] = None


class CohortSlaEvent(EventBase):
    """ADR-064 P2 — a cohort SLA expectation changed state, emitted fail-soft by agent-runtime (sibling of
    ``CohortLifecycleEvent``). The agent-runtime SoR stays authoritative; this is the service-to-service
    signal GLEA (P3) consumes to build the read-model + owner-attributed ``sla_breaches`` rollup — it may
    carry the fields GLEA needs. Fields stay structural/domain-neutral: ``correlation_value``/``ref`` are
    opaque, never business-term keys. Times (``due_at``/``at_risk_at``/``detected_at``) let the read-model
    stay honest about downtime (``detected_at`` may be > ``due_at`` after a crash-recovery re-fire)."""

    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = COHORT_SLA

    schema_version: Literal["pin.platform.cohort_sla/1.0"] = "pin.platform.cohort_sla/1.0"
    cohort_def_id: str
    cohort_instance_id: str
    correlation_value: str                          # opaque business key (structural — not a domain term)
    sla_id: str                                     # stable per-cohort expectation id (e.g. "edge:a->b")
    state: CohortSlaState
    kind: CohortSlaKind
    ref: str                                        # human-readable expectation ref ("a->b" / "a" / "start->close")
    owner: str                                      # external | amendia | shared — the accountable party
    clock: str                                      # wall | business
    due_at: Optional[str] = None                    # the scheduled deadline (ISO) — set on breach
    at_risk_at: Optional[str] = None                # the scheduled at-risk lead (ISO)
    detected_at: Optional[str] = None               # when this transition was noticed (ISO; > due_at if late)
    trace: Optional[Trace] = None


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
