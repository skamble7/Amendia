# app/clickhouse/writer.py
"""The append-only ``audit_events`` writer — glea-service is the SOLE writer of this table.

An insert is idempotent by construction: the table is a ``ReplacingMergeTree`` keyed by
``(correlation_id, occurred_at, event_id)``, so redelivering the same ``event_id`` collapses to one row
on merge (reads use ``FINAL``). On any ClickHouse transport failure the insert raises
``StorageUnavailable`` so the consumer requeues the event rather than acking-and-dropping it.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.clickhouse import schema
from app.clickhouse.client import StorageUnavailable
from app.clickhouse.provider import ClickHousePool
from app.config import settings

logger = logging.getLogger(__name__)


class AuditWriter:
    def __init__(self, pool: ClickHousePool) -> None:
        self._pool = pool
        self._table = f"{settings.CLICKHOUSE_DB}.{settings.CLICKHOUSE_TABLE}"

    def _row_values(self, row: Dict[str, Any]) -> List[Any]:
        return [row.get(col) for col in schema.INSERT_COLUMNS]

    def _insert(self, client: Any, row: Dict[str, Any]) -> None:
        try:
            client.insert(self._table, [self._row_values(row)], column_names=schema.INSERT_COLUMNS)
        except Exception as exc:  # noqa: BLE001 — any insert error → requeue, never drop
            raise StorageUnavailable(f"audit insert failed: {exc}") from exc

    async def insert(self, row: Dict[str, Any]) -> None:
        """Append one audit row on its OWN borrowed client (off the event loop). Raises
        ``StorageUnavailable`` on connect/insert failure so the consumer nacks + requeues."""
        await self._pool.run(lambda client: self._insert(client, row))

    def _reinsert_sealed(self, client: Any, rows: List[Dict[str, Any]]) -> None:
        # Re-insert the identical immutable rows with prev_hash/seal set. ingested_at is NOT written
        # (server DEFAULT now64) → the sealed rows are newer → FINAL returns them. glea stays sole
        # writer; the immutable fields are byte-identical to the originals (else the seal wouldn't verify).
        cols = schema.SEALING_COLUMNS
        data = [[r.get(c) for c in cols] for r in rows]
        try:
            client.insert(self._table, data, column_names=cols)
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"seal reinsert failed: {exc}") from exc

    async def reinsert_sealed(self, rows: List[Dict[str, Any]]) -> None:
        """Persist a computed hash-chain by re-inserting each row with prev_hash/seal set (ADR-058)."""
        if not rows:
            return
        await self._pool.run(lambda client: self._reinsert_sealed(client, rows))
