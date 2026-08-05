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
    "schema_ref",
    "authored_by_human",
    "egress_host",
    "egress_decision",
    "payload",
]

# The read columns a per-instance audit query returns (occurred_at order).
READ_COLUMNS = INSERT_COLUMNS + ["ingested_at"]


def create_database_ddl(db: str) -> str:
    return f"CREATE DATABASE IF NOT EXISTS {db}"


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
