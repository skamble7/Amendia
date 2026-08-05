# app/clickhouse/reader.py
"""Read-side queries over ``audit_events`` (the per-instance audit trail — the Phase B query
foundation; the decision-trail + lineage read-models are Phase C).

Reads use ``FINAL`` so a redelivered/duplicated ``event_id`` shows exactly once."""
from __future__ import annotations

from typing import Any, Dict, List

from app.clickhouse import schema
from app.clickhouse.client import StorageUnavailable
from app.clickhouse.provider import ClickHousePool
from app.config import settings


class AuditReader:
    def __init__(self, pool: ClickHousePool) -> None:
        self._pool = pool
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
        return await self._pool.run(lambda c: self._query_sync(c, correlation_id))

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
        cols = ["element_id", "decided_by", "role", "decision", "sod_satisfied", "occurred_at",
                "payload", "event_id"]
        return await self._pool.run(
            lambda c: self._rows_of_kind_sync(c, correlation_id, "hitl_task_decided", cols))

    async def artifact_rows(self, correlation_id: str) -> List[Dict[str, Any]]:
        # artifact_key was added to the schema after Phase B; rows written before the migration have it
        # empty in the column but present in the stored full-event payload — fall back to that so a
        # redeploy doesn't need a re-run. (Fresh rows populate the column directly.)
        cols = ["element_id",
                "coalesce(nullIf(artifact_key, ''), JSONExtractString(payload, 'artifact_key')) AS artifact_key",
                "schema_ref", "actor", "actor_kind", "authored_by_human", "occurred_at", "event_id"]
        return await self._pool.run(
            lambda c: self._rows_of_kind_sync(c, correlation_id, "artifact_committed", cols))

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
            "toUnixTimestamp64Nano(Timestamp) AS start_ns, "
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
        return await self._pool.run(lambda c: self._trace_tree_sync(c, trace_id))

    async def trace_id_for(self, correlation_id: str) -> str:
        return await self._pool.run(lambda c: self._trace_id_sync(c, correlation_id))

    async def trace_spans(self, trace_id: str) -> List[Dict[str, Any]]:
        return await self._pool.run(lambda c: self._trace_spans_sync(c, trace_id))

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

    # ------------------------------------------------------------------ #
    # ADR-058 hash-chain sealing support (reads)
    # ------------------------------------------------------------------ #
    def _unsealed_quiescent_sync(self, client: Any, quiescent_seconds: int) -> List[str]:
        # Correlations with at least one UNSEALED row and no write in the last N seconds (quiescent).
        sql = (
            f"SELECT correlation_id FROM {self._table} FINAL "
            "WHERE (seal IS NULL OR seal = '') AND correlation_id != '' "
            "GROUP BY correlation_id "
            "HAVING max(ingested_at) < now() - {q:UInt32}"
        )
        try:
            res = client.query(sql, parameters={"q": int(quiescent_seconds)})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"sealing scan failed: {exc}") from exc
        return [str(r[0]) for r in res.result_rows]

    def _sealing_rows_sync(self, client: Any, correlation_id: str) -> List[Dict[str, Any]]:
        cols = ", ".join(schema.SEALING_COLUMNS)
        sql = (f"SELECT {cols} FROM {self._table} FINAL "
               f"WHERE correlation_id = {{cid:String}} ORDER BY occurred_at ASC, event_id ASC")
        try:
            res = client.query(sql, parameters={"cid": correlation_id})
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailable(f"sealing read failed: {exc}") from exc
        return [dict(zip(res.column_names, row)) for row in res.result_rows]

    async def unsealed_quiescent_correlations(self, quiescent_seconds: int) -> List[str]:
        return await self._pool.run(lambda c: self._unsealed_quiescent_sync(c, quiescent_seconds))

    async def sealing_rows(self, correlation_id: str) -> List[Dict[str, Any]]:
        return await self._pool.run(lambda c: self._sealing_rows_sync(c, correlation_id))

    async def metrics_inputs(self, *, correlation_id=None, since=None, until=None) -> Dict[str, Any]:
        # Resolve trace_id + run all aggregates on ONE borrowed client, SEQUENTIALLY (no concurrent
        # queries on it) — a single request never shares its client across threads.
        def op(client: Any) -> Dict[str, Any]:
            trace_id = self._trace_id_sync(client, correlation_id) if correlation_id is not None else None
            return self._metrics_sync(client, correlation_id=correlation_id, since=since, until=until,
                                      trace_id=trace_id)
        return await self._pool.run(op)
