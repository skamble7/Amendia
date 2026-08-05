# CC Prompt — ADR-058 Phase D: aggregate read-models + tiles (ClickHouse SQL, no Prometheus/Grafana)

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md`, the implementation plan (the Phase D table), and the Phase A–C prompts. Phases A (traces+lineage), B (`glea-service` + `audit_events` + governed publishers + native egress), and C (rationale + decision-trail/lineage read-models) are landed and verified. **Phase D adds the aggregate figures** as SQL read-models over `audit_events` + `otel_traces`, to feed the per-instance tiles the frontend renders in Phase E. **There is no Prometheus/Grafana/metrics pipeline** — these are derived by SQL, per ADR-058. **Out of scope:** frontend rendering (Phase E), hash-chain sealing + config-forge publisher (bundled Phase B fast-follow), cross-instance console UI.

## Boundary (unchanged): `glea-service` reads ClickHouse only

Every figure is a **ClickHouse aggregation** over data Phases A/B already persist — `audit_events` (lifecycle, HITL decided, egress, SLA/expiry rows) and `otel_traces` (span durations). No engine changes, no new service, no raw-row pulls into Python — aggregate in the query. Keep the assembly logic pure/unit-testable (like Phase C's `readmodels.py`); the live SQL is exercised at the end-of-track e2e gate.

## Scope

### 1. Per-instance metrics bundle (primary — feeds the Phase E instance tiles)

`GET /audit/instances/{correlation_id}/metrics` → one bundle for the instance (a single endpoint so the frontend fetches once), each figure scoped to that `correlation_id`:

- **Approval latency** (p50/p95): `decided_at − created_at` per gate — join the `HitlTaskCreated` and `HitlTaskDecided` rows for the instance. Join by **`task_id` if the events carry it, else `(correlation_id, element_id)`**; note loop-back re-visits of the same element as an accepted approximation (flag if it turns out to matter).
- **Capability exec duration** (p50/p95): quantiles of the span `Duration` from `otel_traces` for this trace, restricted to capability spans (`SpanAttributes['amendia.actor_kind'] = 'capability'`).
- **HITL decisions by decision + role**: counts grouped by `decision`, `role`.
- **Four-eyes enforced count**: rows where `sod_satisfied` is true.
- **Egress-denied count**: `audit_events` where `egress_decision = 'deny'`.
- **SLA breaches**: `HitlTaskExpired` (and SLA-boundary `TimerFired`) rows for the instance.

Use ClickHouse quantiles (`quantile(0.5)` / `quantile(0.95)`, or `quantileExact`). An instance with no gates / no spans returns a **zeroed/empty** bundle — never an error.

### 2. Platform-wide aggregates (foundation — thin, no UI yet)

`GET /audit/metrics?since=…&until=…` → the same figures **without** the `correlation_id` filter, over a time window, plus **instances by outcome** (counts of `ProcessCompleted` vs `ProcessFailed`). This is the foundation the deferred cross-instance console will use; no frontend consumes it this track, so keep it minimal and parameterized off the **same** query builders as §1 (the only difference is the presence/absence of the `correlation_id` predicate — do not duplicate the SQL).

### 3. Optional — scheduled-query alerting (lower priority; follow-up if not cheap)

A scheduled job in `glea-service` that runs the governance-relevant queries (e.g. egress-deny rate, SLA-breach storm) on an interval and, when a configurable threshold trips, pushes a notification through the **existing `notification-service`** (publish an event it already routes — do not add a new sink). If this is more than a small addition, **leave it as a flagged follow-up** rather than expand Phase D — the tiles are the deliverable.

## Constraints (hard)

- **`glea-service` reads ClickHouse only**; aggregate in SQL (no pulling raw rows to count in Python). Pure, unit-testable assembly over query results; live SQL validated at the e2e gate.
- **Domain-neutral** keys/columns/field names (values may be content). Review gate.
- **Reuse, don't duplicate:** §1 and §2 share query builders parameterized by the optional `correlation_id` predicate.
- **Graceful empties:** missing data → zero/empty figures, never a 500.
- Out of scope: any frontend (Phase E), hash-chain sealing + config-forge publisher (bundled fast-follow), the cross-instance console UI, a Prometheus/Grafana/metrics pipeline.

## Acceptance / exit criteria

1. `GET /audit/instances/{correlation_id}/metrics` returns the full per-instance bundle (approval-latency p50/p95, capability-exec-duration p50/p95, HITL decisions by decision+role, four-eyes-enforced count, egress-denied count, SLA-breach count) for a wire-repair run — each computed as a ClickHouse aggregation; assembly/shape asserted by unit tests over fake rows.
2. `GET /audit/metrics` returns the platform-wide figures incl. **instances by outcome**, from the **same** query builders (correlation_id predicate dropped).
3. An instance with no gates and no capability spans returns a zeroed/empty bundle (no error).
4. Pure ClickHouse reads; domain-neutral; `glea-service` unit suite green (the live-SQL/quantile path is the end-of-track e2e gate — the `Duration`/`SpanAttributes` access is the thing to confirm there, same watch as Phase C's lineage `Links.SpanId`).
5. (If done) the alerting job fires through `notification-service` on a tripped threshold; else it is a clearly-flagged follow-up.

## Working agreement

Supervised: you (CC) write the code; **propose up front** (a) the metrics-bundle response schema, and (b) the aggregate SQL — especially the `HitlTaskCreated`→`HitlTaskDecided` join for approval latency and the capability-span `Duration` quantile — before large edits. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`). Do **not** run the full-stack e2e — single end-of-track gate after all phases.
