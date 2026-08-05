# app/clickhouse/reader.py
"""Read-side queries over ``audit_events`` (the per-instance audit trail — the Phase B query
foundation; the decision-trail + lineage read-models are Phase C).

Reads use ``FINAL`` so a redelivered/duplicated ``event_id`` shows exactly once."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.clickhouse import schema
from app.clickhouse.client import StorageUnavailable
from app.clickhouse.provider import ClickHouseProvider
from app.config import settings


class AuditReader:
    def __init__(self, provider: ClickHouseProvider) -> None:
        self._provider = provider
        self._table = f"{settings.CLICKHOUSE_DB}.{settings.CLICKHOUSE_TABLE}"
        self._cols = schema.READ_COLUMNS

    def _query_sync(self, client: Any, correlation_id: str) -> List[Dict[str, Any]]:
        cols = ", ".join(self._cols)
        sql = (f"SELECT {cols} FROM {self._table} FINAL "
               f"WHERE correlation_id = {{cid:String}} ORDER BY occurred_at ASC, event_id ASC")
        try:
            res = client.query(sql, parameters={"cid": correlation_id})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"audit query failed: {exc}") from exc
        names = res.column_names
        return [dict(zip(names, row)) for row in res.result_rows]

    async def instance_events(self, correlation_id: str) -> List[Dict[str, Any]]:
        client = await self._provider.ensure()
        return await asyncio.to_thread(self._query_sync, client, correlation_id)

    # ------------------------------------------------------------------ #
    # ADR-058 Phase C read-models (pure ClickHouse reads)
    # ------------------------------------------------------------------ #
    def _rows_of_kind_sync(self, client: Any, correlation_id: str, kind: str,
                           cols: List[str]) -> List[Dict[str, Any]]:
        sel = ", ".join(cols)
        sql = (f"SELECT {sel} FROM {self._table} FINAL "
               f"WHERE correlation_id = {{cid:String}} AND kind = {{kind:String}} "
               f"ORDER BY occurred_at ASC, event_id ASC")
        try:
            res = client.query(sql, parameters={"cid": correlation_id, "kind": kind})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"audit query failed: {exc}") from exc
        return [dict(zip(res.column_names, row)) for row in res.result_rows]

    async def decided_rows(self, correlation_id: str) -> List[Dict[str, Any]]:
        client = await self._provider.ensure()
        cols = ["element_id", "decided_by", "role", "decision", "sod_satisfied", "occurred_at",
                "payload", "event_id"]
        return await asyncio.to_thread(self._rows_of_kind_sync, client, correlation_id,
                                       "hitl_task_decided", cols)

    async def artifact_rows(self, correlation_id: str) -> List[Dict[str, Any]]:
        client = await self._provider.ensure()
        cols = ["element_id", "artifact_key", "schema_ref", "actor", "actor_kind",
                "authored_by_human", "occurred_at", "event_id"]
        return await asyncio.to_thread(self._rows_of_kind_sync, client, correlation_id,
                                       "artifact_committed", cols)

    def _trace_id_sync(self, client: Any, correlation_id: str) -> str:
        sql = (f"SELECT trace_id FROM {self._table} FINAL "
               f"WHERE correlation_id = {{cid:String}} AND trace_id != '' LIMIT 1")
        try:
            res = client.query(sql, parameters={"cid": correlation_id})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"audit query failed: {exc}") from exc
        return str(res.result_rows[0][0]) if res.result_rows else ""

    def _trace_spans_sync(self, client: Any, trace_id: str) -> List[Dict[str, Any]]:
        # Pure read over the OTel Collector's otel_traces schema: the amendia.* span attributes carry
        # each node's artifact identity, and Links.SpanId are the lineage edges (producer spans).
        sql = (
            "SELECT SpanId AS span_id, "
            "SpanAttributes['amendia.element_id'] AS element_id, "
            "SpanAttributes['amendia.artifact_key'] AS artifact_key, "
            "SpanAttributes['amendia.schema_ref'] AS schema_ref, "
            "SpanAttributes['amendia.actor_kind'] AS actor_kind, "
            "Links.SpanId AS link_span_ids "
            "FROM otel.otel_traces WHERE TraceId = {tid:String}"
        )
        try:
            res = client.query(sql, parameters={"tid": trace_id})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"trace query failed: {exc}") from exc
        return [dict(zip(res.column_names, row)) for row in res.result_rows]

    def _trace_tree_sync(self, client: Any, trace_id: str) -> List[Dict[str, Any]]:
        # The instance's spans for the in-view execution waterfall (ADR-058 §6). otel_traces only.
        sql = (
            "SELECT SpanId AS span_id, ParentSpanId AS parent_span_id, SpanName AS name, "
            "toUnixTimestamp64Nano(Timestamp) AS start_ns, Duration AS duration_ns, "
            "SpanAttributes['amendia.element_id'] AS element_id, "
            "SpanAttributes['amendia.actor'] AS actor, "
            "SpanAttributes['amendia.actor_kind'] AS actor_kind, "
            "SpanAttributes['amendia.artifact_key'] AS artifact_key "
            "FROM otel.otel_traces WHERE TraceId = {tid:String} "
            "ORDER BY Timestamp ASC, SpanId ASC"
        )
        try:
            res = client.query(sql, parameters={"tid": trace_id})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"trace query failed: {exc}") from exc
        return [dict(zip(res.column_names, row)) for row in res.result_rows]

    async def trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        client = await self._provider.ensure()
        return await asyncio.to_thread(self._trace_tree_sync, client, trace_id)

    async def trace_id_for(self, correlation_id: str) -> str:
        client = await self._provider.ensure()
        return await asyncio.to_thread(self._trace_id_sync, client, correlation_id)

    async def trace_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        client = await self._provider.ensure()
        return await asyncio.to_thread(self._trace_spans_sync, client, trace_id)

    # ------------------------------------------------------------------ #
    # ADR-058 Phase D aggregate tiles — everything aggregates IN ClickHouse.
    # §1 (per-instance) and §2 (platform-wide) share this one builder; the ONLY difference is the
    # scope predicate: ``correlation_id = …`` vs an ``occurred_at`` time window.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _one(res) -> Dict[str, Any]:
        return dict(zip(res.column_names, res.result_rows[0])) if res.result_rows else {}

    @staticmethod
    def _rows(res) -> List[Dict[str, Any]]:
        return [dict(zip(res.column_names, r)) for r in res.result_rows]

    def _metrics_sync(self, client: Any, *, correlation_id, since, until, trace_id) -> Dict[str, Any]:
        audit = self._table
        if correlation_id is not None:
            scope, base = "correlation_id = {cid:String}", {"cid": correlation_id}
        else:
            scope = "occurred_at BETWEEN {since:DateTime64(3)} AND {until:DateTime64(3)}"
            base = {"since": since, "until": until}

        def q(sql: str, extra=None):
            try:
                return client.query(sql, parameters={**base, **(extra or {})})
            except Exception as exc:  # noqa: BLE001
                raise StorageUnavailable(f"metrics query failed: {exc}") from exc

        # Approval latency (ms): decided_at − created_at per HITL task, joined by task_id (carried in
        # the event payload) so loop-back re-visits of the same element don't conflate.
        latency = self._one(q(f"""
            WITH created AS (
              SELECT JSONExtractString(payload, 'task_id') AS task_id, min(occurred_at) AS created_at
              FROM {audit} FINAL WHERE kind = 'hitl_task_created' AND {scope} GROUP BY task_id),
            decided AS (
              SELECT JSONExtractString(payload, 'task_id') AS task_id, min(occurred_at) AS decided_at
              FROM {audit} FINAL WHERE kind = 'hitl_task_decided' AND {scope} GROUP BY task_id)
            SELECT quantileExact(0.5)(d) AS p50, quantileExact(0.95)(d) AS p95, count() AS count
            FROM (SELECT dateDiff('millisecond', created_at, decided_at) AS d
                  FROM created INNER JOIN decided USING (task_id) WHERE task_id != '')
        """))

        # Capability exec duration (ms): span Duration quantiles over the capability spans of this
        # trace (per-instance) or the window (platform-wide). Duration is nanoseconds → /1e6 = ms.
        if trace_id is not None:
            dur_scope, dur_extra = "TraceId = {tid:String}", {"tid": trace_id}
        else:
            dur_scope = "Timestamp BETWEEN {since:DateTime64(9)} AND {until:DateTime64(9)}"
            dur_extra = {}
        duration = self._one(q(f"""
            SELECT quantileExact(0.5)(Duration / 1000000) AS p50,
                   quantileExact(0.95)(Duration / 1000000) AS p95, count() AS count
            FROM otel.otel_traces
            WHERE {dur_scope} AND SpanAttributes['amendia.actor_kind'] = 'capability'
        """, dur_extra))

        decisions = self._rows(q(f"""
            SELECT decision, role, count() AS count FROM {audit} FINAL
            WHERE kind = 'hitl_task_decided' AND {scope}
            GROUP BY decision, role ORDER BY count DESC, decision, role
        """))
        four_eyes = self._one(q(f"""
            SELECT count() AS n FROM {audit} FINAL
            WHERE kind = 'hitl_task_decided' AND sod_satisfied = 1 AND {scope}
        """)).get("n", 0)
        egress_denied = self._one(q(f"""
            SELECT count() AS n FROM {audit} FINAL WHERE egress_decision = 'deny' AND {scope}
        """)).get("n", 0)
        sla_breaches = self._one(q(f"""
            SELECT count() AS n FROM {audit} FINAL
            WHERE (kind = 'hitl_task_expired'
                   OR (kind = 'timer_fired' AND JSONExtractString(payload, 'kind') = 'boundary'))
              AND {scope}
        """)).get("n", 0)

        inputs: Dict[str, Any] = {
            "latency": latency, "duration": duration, "decisions": decisions,
            "four_eyes": four_eyes, "egress_denied": egress_denied, "sla_breaches": sla_breaches,
        }
        # Instances-by-outcome is a platform-wide-only figure (a single instance has one outcome).
        if correlation_id is None:
            inputs["outcome"] = self._one(q(f"""
                SELECT countIf(kind = 'process_completed') AS completed,
                       countIf(kind = 'process_failed') AS failed
                FROM {audit} FINAL WHERE {scope}
            """))
        return inputs

    async def metrics_inputs(self, *, correlation_id=None, since=None, until=None) -> Dict[str, Any]:
        client = await self._provider.ensure()
        trace_id = None
        if correlation_id is not None:
            trace_id = await asyncio.to_thread(self._trace_id_sync, client, correlation_id)
        return await asyncio.to_thread(
            self._metrics_sync, client,
            correlation_id=correlation_id, since=since, until=until, trace_id=trace_id)
