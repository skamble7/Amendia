# CC Prompt — glea audit_events missing `artifact_key` column (decision-trail + lineage 503)

**Priority: fixes the two GLEA sections still showing "unavailable" after the live e2e** (decision-trail, lineage). glea is healthy; metrics/audit/trace return 200 — only these two 503. Unit tests missed it because the fake ClickHouse client returns rows regardless of whether the selected columns exist.

## Root cause (confirmed in code)

`reader.artifact_rows` selects `artifact_key` from `audit_events`:
```
cols = ["element_id", "artifact_key", "schema_ref", "actor", "actor_kind", "authored_by_human", "occurred_at", "event_id"]
```
but the `audit_events` schema (`clickhouse/schema.py`) has **no `artifact_key` column** — it defines `schema_ref` and `authored_by_human` but not `artifact_key`, and `events/mapper.py` never writes one. So the query raises ClickHouse "unknown identifier: artifact_key" → `StorageUnavailable` → **503**.

`artifact_rows` is the shared dependency of exactly the two failing endpoints and none of the working ones — that's the partition:
- **decision-trail** = `decided_rows` + **`artifact_rows`** → 503
- **lineage** = `trace_spans` + **`artifact_rows`** → 503
- audit list (`instance_events`), metrics (`metrics_inputs`), trace (`trace_tree`) never call `artifact_rows` → 200

`artifact_key` is under-specified: `ArtifactCommittedEvent` (Phase B) carries it and the Phase C read-models key on it, but the Phase B schema/mapper dropped it (only `schema_ref`/`authored_by_human` landed).

## Fix

Make `artifact_key` a first-class column (it is a real audit field the read-models join on — consistent with `schema_ref`/`element_id` being columns):

1. **schema.py** — add `artifact_key String` to the `audit_events` DDL (near `schema_ref`).
2. **Migrate existing tables idempotently** — the bootstrap uses `CREATE TABLE IF NOT EXISTS`, which will NOT add a column to an already-created table. Add, in bootstrap, an idempotent `ALTER TABLE {db}.audit_events ADD COLUMN IF NOT EXISTS artifact_key String` so a redeploy over an existing DB gains the column without a drop.
3. **mapper.py** — populate `artifact_key` from the `ArtifactCommittedEvent` payload (`payload.get("artifact_key")`), alongside `schema_ref`/`authored_by_human`. Other event kinds leave it "".
4. **Rows written before the migration** (e.g. this run's `artifact_committed` rows) will have an empty `artifact_key` column. To resolve those without forcing a re-run, make `artifact_rows` fall back to the payload: `coalesce(nullIf(artifact_key,''), JSONExtractString(payload,'artifact_key'))` — **first verify** `artifact_key` is actually present in the stored `payload` JSON; if the mapper does not store the full event body in `payload`, skip the fallback and note that a fresh run is needed to populate the new column. (A fresh restaurant/wire run after the fix is an acceptable validation either way.)

## Verify

- **Schema-vs-readers consistency test** (this is what would have caught it): assert that every column each reader method SELECTs from `audit_events` is present in the schema DDL — or make the test `FakeClient` raise on an unknown column (model ClickHouse's behavior) so `artifact_rows` selecting a non-schema column fails in unit tests. The current fake returns rows regardless; that gap let this through.
- Existing glea unit suite stays green.
- Post-deploy against the live stack: `GET /audit/instances/{cid}/decision-trail` and `…/lineage` return **200 with data** (audit/metrics/trace still 200). In the UI, the Governance tab's Decision trail and the Observability tab's Lineage populate.
- **Standing watch (now reachable):** once past the 503, confirm the **lineage `edges` are non-empty** — the `_trace_spans_sync` `Links.SpanId` array extraction is the last unverified live-SQL assumption. If nodes render but edges are empty, that array access needs adjusting for the otel_traces schema (separate, small; flag it and I'll pair on it).

## Working agreement

Supervised: you (CC) write the code; note whether `payload` carries `artifact_key` (drives step 4) and propose the schema + mapper + reader changes before applying. glea remains the sole writer of `audit_events`; domain-neutral. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).
