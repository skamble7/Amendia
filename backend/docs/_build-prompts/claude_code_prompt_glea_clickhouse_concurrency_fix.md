# CC Prompt — glea-service ClickHouse client concurrency fix (e2e blocker)

**Priority: blocks the ADR-058 end-of-track e2e.** The full-stack run surfaced this; unit tests missed it because they mock ClickHouse (a mock doesn't enforce session concurrency).

## Symptom (from the live glea-service logs)

Both the write path (consumer) and read path (audit API) fail with:

```
audit insert failed: Attempt to execute concurrent queries within the same session.
Please use a separate client instance per thread/process.
```

Consequences observed: every audit insert fails → `nack+requeue` (a requeue storm — the same routing keys logged dozens of times), so `glea.audit_events` is **never written / stays empty**; every read endpoint returns **503**; and because the same client backs the `otel_traces` reads, the lineage/metrics/trace endpoints fail too. The frontend then (correctly) degrades every GLEA section to "unavailable."

## Root cause

`backend/services/platform/glea-service/app/clickhouse/provider.py` caches a **single** `clickhouse-connect` client (`self._client`) and returns that same instance from `ensure()` to **every** caller — the async consumer's inserts (run via `asyncio.to_thread`) and all read-API queries. `clickhouse-connect`'s HTTP client carries a **session** (session_id) and is **not safe for concurrent queries / concurrent use across threads**. Under real concurrent load (consumer draining the queue while the read API polls), queries collide in the one session → the error above.

## Fix

1. **Stop sharing one client across concurrent operations.** Give each concurrent operation its own client. Preferred: a small **connection pool** sized to the blocking thread-pool (each pooled client used by one query at a time); acceptable-simplest: **create-and-close a client per operation**. Keep the **one-time schema bootstrap** (`CREATE DATABASE/TABLE IF NOT EXISTS`) on startup / first-use, separate from the per-operation clients — don't bootstrap per query.
2. **No shared session.** Connect with `autogenerate_session_id=False` (sessionless) so pooled/per-op clients can't collide on a session_id, and never reuse one `Client` object for concurrent queries across threads. (Sessionless alone is not sufficient if one `Client` is still shared across threads — the client-per-op / pool is the real fix; disabling the session is belt-and-suspenders.)
3. **Preserve the existing contracts:** fail-soft (`StorageUnavailable` → consumer nack/requeue, read API 503); idempotent writes (`ReplacingMergeTree` keyed by the dedup tuple, reads use `FINAL`); glea remains the **sole writer** of `audit_events`.
4. **Secondary hardening (small, do if cheap):** the requeue on `StorageUnavailable` currently hot-loops when ClickHouse is persistently down (CPU/log spam). Add a brief backoff before requeue, or a dead-letter after N attempts, so a real outage doesn't spin. Do not change the no-loss guarantee.

## Verify

- A **regression test** that exercises **concurrent inserts + a concurrent read** through the provider/client abstraction and would FAIL on a shared-session/shared-client reuse — e.g. fire N audit inserts and a read simultaneously and assert all succeed, or assert the pool/factory hands **distinct** client instances to concurrent callers. The fake/mock must model the "one session = no concurrent queries" constraint (or use a real ClickHouse in an integration-marked test); a mock that ignores concurrency is what let this through.
- Existing glea unit suite stays green; the fail-soft and idempotency tests still hold.
- Manual/e2e expectation after deploy: a restaurant/wire run writes `audit_events` rows (the **durable-queue backlog from the failed run drains on its own** once writes succeed — no re-run needed unless RabbitMQ was wiped), and `GET /audit/instances/{cid}` + `…/decision-trail` + `…/lineage` + `…/metrics` + `…/trace` all return **200 with data** (and the same-run `correlation_id`/`trace_id` join to `otel.otel_traces`).

## Working agreement

Supervised: you (CC) write the code; propose the pool-vs-per-op choice + the connect-args change before large edits. Note: `webui/nginx.conf` already proxies `/api/glea/` → `glea-service:8090` correctly — no proxy change needed. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).
