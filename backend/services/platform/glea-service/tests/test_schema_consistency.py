# tests/test_schema_consistency.py
"""Guard: every column the readers SELECT from audit_events must exist in the schema DDL.

This is what the unit suite was missing — the fake ClickHouse client returns rows regardless of whether
the selected columns exist, so ``reader.artifact_rows`` selecting a non-existent ``artifact_key`` slipped
through to a live 503 ("unknown identifier: artifact_key"). Parsing the DDL + the idempotent ALTERs and
asserting coverage catches that class at unit time.
"""
from __future__ import annotations

import re

from app.clickhouse import schema


def _schema_columns() -> set[str]:
    """The column names the audit_events table has: the CREATE TABLE column list + any ALTER-added
    columns. Parses only the column-list block (up to its closing paren), then the ALTER migrations."""
    ddl = schema.create_table_ddl("glea", "audit_events", 30)
    body = ddl.split("(", 1)[1]  # everything after `CREATE TABLE … (`
    cols: set[str] = set()
    for raw in body.splitlines():
        line = raw.strip().rstrip(",")
        if line.startswith(")"):  # end of the column list — stop before ENGINE/ORDER BY/TTL
            break
        if not line or line.startswith("--"):
            continue
        cols.add(line.split()[0])
    for alter in schema.alter_add_columns_ddl("glea", "audit_events"):
        m = re.search(r"ADD COLUMN IF NOT EXISTS (\w+)", alter)
        if m:
            cols.add(m.group(1))
    return cols


# The base audit_events columns the readers SELECT or reference in an expression (reader.py). A column
# missing from the schema → a live "unknown identifier" → StorageUnavailable → 503.
READER_BASE_COLUMNS = {
    "event_id", "occurred_at", "ingested_at", "kind", "correlation_id", "trace_id",
    "actor", "actor_kind", "role", "element_id", "pack_key", "pack_version",
    "decision", "decided_by", "sod_satisfied", "artifact_key", "schema_ref",
    "authored_by_human", "egress_host", "egress_decision", "payload",
}


def test_schema_covers_every_reader_column():
    missing = READER_BASE_COLUMNS - _schema_columns()
    assert not missing, f"readers reference columns absent from the schema DDL: {sorted(missing)}"


def test_insert_and_read_columns_exist_in_schema():
    cols = _schema_columns()
    assert set(schema.INSERT_COLUMNS) <= cols, sorted(set(schema.INSERT_COLUMNS) - cols)
    assert set(schema.READ_COLUMNS) <= cols, sorted(set(schema.READ_COLUMNS) - cols)


def test_artifact_key_is_a_first_class_column():
    # The specific regression: artifact_key must be written (INSERT) AND in the schema.
    assert "artifact_key" in schema.INSERT_COLUMNS
    assert "artifact_key" in _schema_columns()
