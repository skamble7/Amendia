# app/clickhouse/writer.py
"""The append-only ``audit_events`` writer — glea-service is the SOLE writer of this table.

An insert is idempotent by construction: the table is a ``ReplacingMergeTree`` keyed by
``(correlation_id, occurred_at, event_id)``, so redelivering the same ``event_id`` collapses to one row
on merge (reads use ``FINAL``). On any ClickHouse transport failure the insert raises
``StorageUnavailable`` so the consumer requeues the event rather than acking-and-dropping it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from app.clickhouse import schema
from app.clickhouse.client import StorageUnavailable
from app.clickhouse.provider import ClickHouseProvider
from app.config import settings

logger = logging.getLogger(__name__)


class AuditWriter:
    def __init__(self, provider: ClickHouseProvider) -> None:
        self._provider = provider
        self._table = f"{settings.CLICKHOUSE_DB}.{settings.CLICKHOUSE_TABLE}"

    def _row_values(self, row: Dict[str, Any]) -> List[Any]:
        return [row.get(col) for col in schema.INSERT_COLUMNS]

    def _insert_sync(self, client: Any, row: Dict[str, Any]) -> None:
        try:
            client.insert(self._table, [self._row_values(row)], column_names=schema.INSERT_COLUMNS)
        except Exception as exc:  # noqa: BLE001 — any insert error → requeue, never drop
            raise StorageUnavailable(f"audit insert failed: {exc}") from exc

    async def insert(self, row: Dict[str, Any]) -> None:
        """Append one audit row (blocking driver call runs off the event loop). Raises
        ``StorageUnavailable`` on failure so the consumer nacks + requeues."""
        client = await self._provider.ensure()          # raises StorageUnavailable if CH is down
        await asyncio.to_thread(self._insert_sync, client, row)
