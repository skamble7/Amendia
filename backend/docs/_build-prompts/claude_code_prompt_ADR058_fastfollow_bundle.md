# CC Prompt — ADR-058 fast-follow bundle: config-forge publisher · hash-chain sealing · lineage dedupe

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md` (now Accepted) and the Phase B/C prompts. ADR-058 A–E is landed and validated live. This bundles the three deferred/cosmetic tails. They are **independent** — do them in one pass. Out of scope: Phase D §3 scheduled-query alerting (still optional, separate). glea remains the **sole writer** of `audit_events`; all fields structural/domain-neutral; fail-soft; no new deps; supervised.

## 1. config-forge `ConfigRefResolvedEvent` publisher (deferred from Phase B)

The `ConfigRefResolvedEvent` contract exists and `glea-service` already binds its routing key — only the **publisher** is missing (config-forge was the older `@app.on_event` service with no broker plumbing, so it was deferred).

- Add a **fail-soft RabbitMQ publisher** to config-forge, mirroring the existing pattern in agent-runtime / identity / process-registry (the durable `amendia.events` topic exchange). Publish `ConfigRefResolvedEvent` at the config/credential-ref **resolution point**, stamping `trace_id` from the current OTel context (`amendia_telemetry.current_traceparent()`).
- **Fail-soft:** a broker hiccup never breaks a config resolution.
- **Verify:** resolving a config ref lands a `config_ref_resolved` row in `audit_events` (via glea's existing binding); config-forge boots; resolution still succeeds when the broker is down.

## 2. Hash-chain sealing (deferred tamper-evidence from Phase B)

`audit_events` already reserves `prev_hash`/`seal` (never populated). Implement a per-`correlation_id` append-only **hash-chain** so tampering with a sealed row is detectable.

- **Sealing pass** in glea-service (periodic, or triggered when an instance is quiescent): for each `correlation_id` with unsealed rows, order events deterministically by `(occurred_at, event_id)`, compute `seal[i] = H(canonical_row[i] || prev_hash[i])` with `prev_hash[i] = seal[i-1]` (genesis `prev_hash = ""`). `canonical_row` = a **stable, field-ordered** serialization of the immutable audit fields, **excluding** `ingested_at`/`prev_hash`/`seal` from the hash input.
- **Persist without a ClickHouse mutation:** because `audit_events` is `ReplacingMergeTree(ingested_at)`, seal by **re-inserting the same `event_id` row with `prev_hash`/`seal` set and a newer `ingested_at`** — `FINAL` reads then return the sealed version. (Recommended over `ALTER … UPDATE` mutations; confirm the re-insert collapses correctly under the existing dedup tuple.)
- **Only seal quiescent correlations** (instance completed, or no new events for N seconds) so an in-flight instance isn't sealed mid-write.
- **Verification path:** given a `correlation_id`, recompute the chain over the stored rows and report **intact / broken** (a function + optional endpoint). Sealing an already-sealed correlation is a **no-op** (same seals recomputed) — idempotent.
- **Verify:** a completed run's rows gain `prev_hash`/`seal`; recomputation reports intact; a test that mutates a sealed row's content detects **broken**; re-running the sealer is idempotent; reads are never blocked.

## 3. Lineage node dedupe (cosmetic; observed live)

The lineage graph renders **duplicate nodes** for HITL-gated artifacts: a HITL task emits two node spans (park + resume), both carrying the same `amendia.artifact_key`, and `build_lineage` keys nodes by `span_id` → two boxes for one logical artifact (seen live: two `rest_stan.order`, `prepared`, `served`, …).

- In `build_lineage` (`readmodels.py`), **collapse nodes by `(element_id, artifact_key)`** — one node per logical artifact (prefer the later/resume producer span), re-point edges to the kept node id, and dedupe resulting parallel edges. Nodes without an `artifact_key` are unaffected. Pure assembler change.
- **Verify:** a unit test with fake rows containing a park+resume duplicate → one node, edges preserved; the MI join fan-in (where present) is unaffected; live, the restaurant run shows one node per artifact.

## Overall verify

glea + config-forge unit suites green; a live run shows `config_ref_resolved` audit rows, `prev_hash`/`seal` populated on a completed instance with an **intact** verification, and a **deduped** lineage graph.

## Working agreement

Supervised: you (CC) write the code; **propose up front** (a) the config-forge publisher wiring, (b) the sealing mechanism (re-insert vs. separate table — recommend re-insert given the reserved columns) + the `canonical_row` definition, and (c) the dedupe key, before large edits. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).
