# app/clickhouse/schema.py
"""The append-only ``audit_events`` system-of-record schema (ADR-058 Phase B).

glea-service is the SOLE writer of this table. All columns are structural / domain-neutral — no pack or
business term. Idempotency (at-least-once delivery ⇒ dedupe) rides on ``ReplacingMergeTree`` keyed by the
sorting tuple ``(correlation_id, occurred_at, event_id)``: a redelivered ``event_id`` has an identical
tuple and collapses on merge; reads use ``FINAL`` for immediate dedupe. Retention is a TTL on
``occurred_at`` (a long audit horizon, independent of the operational-trace TTL).

**Hash-chain readiness (deferred fast-follow):** ``prev_hash`` and ``seal`` columns exist so the
tamper-evidence chaining can land without a migration — they are **never populated in Phase B**.
"""
from __future__ import annotations

# Column order for INSERTs. Excludes ``ingested_at`` (server DEFAULT now64) and the reserved
# ``prev_hash``/``seal`` (left NULL in Phase B).
INSERT_COLUMNS = [
    "event_id",
    "occurred_at",
    "kind",
    "correlation_id",
    "trace_id",
    "actor",
    "actor_kind",
    "role",
    "element_id",
    "pack_key",
    "pack_version",
    "decision",
    "decided_by",
    "sod_satisfied",
    "artifact_key",
    "schema_ref",
    "authored_by_human",
    "egress_host",
    "egress_decision",
    "payload",
]

# The read columns a per-instance audit query returns (occurred_at order).
READ_COLUMNS = INSERT_COLUMNS + ["ingested_at"]

# The columns the sealing pass reads/writes: the immutable audit fields + the chain columns. ``ingested_at``
# is deliberately excluded from INSERT_COLUMNS (server DEFAULT now64) so a re-insert of a sealed row gets a
# NEWER ingested_at and wins under ReplacingMergeTree(ingested_at).
SEALING_COLUMNS = INSERT_COLUMNS + ["prev_hash", "seal"]


def create_database_ddl(db: str) -> str:
    return f"CREATE DATABASE IF NOT EXISTS {db}"


def alter_add_columns_ddl(db: str, table: str) -> list[str]:
    """Idempotent column migrations for a table that predates a schema addition. ``CREATE TABLE IF NOT
    EXISTS`` won't add a column to an existing table, so a redeploy over an existing DB runs these to
    gain the new column without a drop. ``artifact_key`` (the join key the decision-trail + lineage
    read-models select) was missing from the original Phase B schema."""
    return [
        f"ALTER TABLE {db}.{table} ADD COLUMN IF NOT EXISTS artifact_key String AFTER sod_satisfied",
    ]


# --------------------------------------------------------------------------- #
# ADR-063 Phase 3A — the cohort read-model table (a SEPARATE table from audit_events, which is sorted by
# correlation_id and has no cohort columns). Sourced from the CohortLifecycleEvent stream; cohort reads query
# by cohort_instance_id. Idempotent on event_id via the sort tuple. audit_events is untouched.
# --------------------------------------------------------------------------- #
COHORT_INSERT_COLUMNS = [
    "event_id",
    "occurred_at",
    "op",
    "cohort_instance_id",
    "cohort_def_id",
    "correlation_value",
    "member_process_instance_id",
    "member_pack_key",
    "member_pack_version",
    "member_correlation_id",       # the member instance's correlation_id — join key into audit_events
    "close_outcome",
    "detail",
    "trace_id",
]
COHORT_READ_COLUMNS = COHORT_INSERT_COLUMNS + ["ingested_at"]


def cohort_alter_add_columns_ddl(db: str, table: str) -> list[str]:
    """Idempotent column migrations for a pre-existing cohort_events table. Empty today (fresh table); the
    sibling of ``alter_add_columns_ddl`` so future additive columns land without a drop."""
    return []


def create_cohort_table_ddl(db: str, table: str, ttl_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {db}.{table} (
  event_id                    String,
  occurred_at                 DateTime64(3, 'UTC'),
  ingested_at                 DateTime64(3, 'UTC') DEFAULT now64(3),
  op                          LowCardinality(String),
  cohort_instance_id          String,
  cohort_def_id               String,
  correlation_value           String,
  member_process_instance_id  String,
  member_pack_key             String,
  member_pack_version         String,
  member_correlation_id       String,
  close_outcome               String,
  detail                      String,
  trace_id                    String
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (cohort_instance_id, occurred_at, event_id)
TTL toDateTime(occurred_at) + INTERVAL {int(ttl_days)} DAY
SETTINGS index_granularity = 8192
""".strip()


# --------------------------------------------------------------------------- #
# ADR-064 P3 — the cohort SLA read-model table (a SEPARATE table again — audit_events and cohort_events are
# untouched). Sourced from the CohortSlaEvent stream (agent_runtime.cohort_sla.v1). The current state of an
# expectation is the latest event per sla_id, so the ORDER BY leads with (cohort_instance_id, sla_id) → the
# per-sla_id latest is a cheap read. Idempotent on event_id via the sort tuple (ReplacingMergeTree on
# ingested_at). due_at/at_risk_at/detected_at are stored as the emitted ISO strings (may be "" when absent),
# lossless and parse-free — the UI renders them.
# --------------------------------------------------------------------------- #
COHORT_SLA_INSERT_COLUMNS = [
    "event_id",
    "occurred_at",
    "state",
    "cohort_instance_id",
    "cohort_def_id",
    "correlation_value",
    "sla_id",
    "kind",
    "ref",
    "owner",
    "clock",
    "due_at",
    "at_risk_at",
    "detected_at",
]
COHORT_SLA_READ_COLUMNS = COHORT_SLA_INSERT_COLUMNS + ["ingested_at"]


def cohort_sla_alter_add_columns_ddl(db: str, table: str) -> list[str]:
    """Idempotent column migrations for a pre-existing cohort_sla_events table. Empty today (fresh table);
    the sibling of ``cohort_alter_add_columns_ddl`` so future additive columns land without a drop."""
    return []


def create_cohort_sla_table_ddl(db: str, table: str, ttl_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {db}.{table} (
  event_id            String,
  occurred_at         DateTime64(3, 'UTC'),
  ingested_at         DateTime64(3, 'UTC') DEFAULT now64(3),
  state               LowCardinality(String),
  cohort_instance_id  String,
  cohort_def_id       String,
  correlation_value   String,
  sla_id              String,
  kind                LowCardinality(String),
  ref                 String,
  owner               LowCardinality(String),
  clock               LowCardinality(String),
  due_at              String,
  at_risk_at          String,
  detected_at         String
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (cohort_instance_id, sla_id, occurred_at, event_id)
TTL toDateTime(occurred_at) + INTERVAL {int(ttl_days)} DAY
SETTINGS index_granularity = 8192
""".strip()


def create_table_ddl(db: str, table: str, ttl_days: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {db}.{table} (
  event_id          String,
  occurred_at       DateTime64(3, 'UTC'),
  ingested_at       DateTime64(3, 'UTC') DEFAULT now64(3),
  kind              LowCardinality(String),
  correlation_id    String,
  trace_id          String,
  actor             String,
  actor_kind        LowCardinality(String),
  role              String,
  element_id        String,
  pack_key          String,
  pack_version      String,
  decision          LowCardinality(String),
  decided_by        String,
  sod_satisfied     Nullable(UInt8),
  artifact_key      String,
  schema_ref        String,
  authored_by_human Nullable(UInt8),
  egress_host       String,
  egress_decision   LowCardinality(String),
  payload           String,
  -- RESERVED for the deferred hash-chain fast-follow — present in the schema, NEVER written in Phase B.
  prev_hash         Nullable(String),
  seal              Nullable(String)
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (correlation_id, occurred_at, event_id)
TTL toDateTime(occurred_at) + INTERVAL {int(ttl_days)} DAY
SETTINGS index_granularity = 8192
""".strip()
