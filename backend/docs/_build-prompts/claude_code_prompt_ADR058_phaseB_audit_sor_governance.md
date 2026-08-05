# CC Prompt — ADR-058 Phase B: audit system-of-record (`glea-service`) + governed-event publishers + native egress enforcement

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md`, the implementation plan (`backend/docs/engineering/amendia_glea_otel_implementation_plan.md`), and the Phase A prompt + closeout. Phase A (telemetry foundation: traces + lineage in ClickHouse, both modes) is landed and verified. **Phase B builds the durable audit system-of-record on the RabbitMQ backbone.** Hash-chain tamper-evidence is **deferred to a fast-follow** — Phase B lands **append-only + TTL** and leaves the schema *ready* for chaining, but does **not** implement sealing. Phases C (rationale + decision-trail/lineage read-models), D (aggregate tiles), and E (frontend) remain out of scope.

## The design (from ADR-058 §2–3)

Governed business events travel the existing **`amendia.events`** durable topic exchange (the one `notification-service` already consumes). A new **`glea-service`** consumes them on its **own durable, named queue** and **persists** them append-only into ClickHouse `audit_events` — it is the **sole writer** of that table. Traces (Phase A) and audit events (Phase B) join on `correlation_id` + `trace_id`. `agent-runtime` and the other services stay pure producers; only `glea-service` touches ClickHouse for audit.

## Scope

### 1. Audit-event contracts (`libs/amendia_contracts/amendia_contracts/`)

Follow the existing event shape (each event is a typed model with `event_id`, `to_doc()`, `routing_key()`; routing keys on the `amendia.events` topic). All fields **structural / domain-neutral**. Every audit-relevant event MUST carry `correlation_id` **and** `trace_id` (the join key to `otel_traces`) plus `occurred_at`.

- **Enrich existing events** so they double as audit records: add `trace_id` (and `correlation_id` if missing) to `ProcessCompletedEvent`, `ProcessFailedEvent`, `HitlTaskCreatedEvent`, `HitlTaskExpiredEvent`, `TimerFiredEvent`, `MessageReceivedEvent`, and **`HitlTaskDecidedEvent`** (add `decision`, `decided_by`, `role`, `sod_satisfied`). Keep existing consumers working (additive fields).
- **New events** for governed decision points that have none today (put in a new `governance_events.py`):
  - `EgressDecisionEvent` — `decision` (`allow`|`deny`), `host`, capability id, `execution_mode`, `element_id`, `correlation_id`, `trace_id`.
  - `ArtifactCommittedEvent` — `artifact_key`, `schema_ref`, `authored_by_human`, `element_id`, `actor`, `correlation_id`, `trace_id`.
  - `RoleChangedEvent` (identity) — `subject_user`, `role`, `op` (`grant`|`revoke`), `actor`, outcome (incl. admin-/last-admin-protection refusals).
  - `PackLifecycleEvent` (process-registry) — `pack_key`, `version`, `op` (`publish`|`deprecate`|`rollback`), `actor`.
  - `ConfigRefResolvedEvent` (config-forge) — **lower priority**; include if cheap, else note as a follow-up.

### 2. Publishers — emit governed events + stamp `trace_id`

Stamp `trace_id` from the current OTel context (`amendia_telemetry.current_traceparent()` / the persisted `state.trace["otel"]`) at emit time, so every audit row joins to its trace.

- **agent-runtime**: enrich the `HitlTaskDecidedEvent` publish in `hitl_service.decide` with `sod_satisfied`/`decision`/`decided_by`/`role`; publish `ArtifactCommittedEvent` from the commit path (`_commit`); publish `EgressDecisionEvent` from the egress path (item 4); add `trace_id` to the existing lifecycle publishes in `engine.py`.
- **identity**: publish `RoleChangedEvent` on grant/revoke and on admin-/last-admin-protection outcomes (`guardrails.py`).
- **process-registry**: publish `PackLifecycleEvent` on publish/deprecate/rollback.
- **config-forge**: `ConfigRefResolvedEvent` if cheap (else follow-up).

All via the existing `amendia.events` exchange. Publishing must be fail-soft (a broker hiccup never breaks the governed action).

### 3. New service `glea-service` (`backend/services/platform/glea-service`)

- **Consumer** — a **durable, named** queue (competing-consumers / work-queue semantics), bound to the audit-relevant routing keys. **Do NOT copy notification-service's broadcast (exclusive/auto-delete) queue** — that pattern drops messages when the consumer is down; audit must lose nothing. Standard connect/backoff loop like the other durable consumers.
- **ClickHouse writer** — the **sole writer** of `audit_events`. Insert is **idempotent by `event_id`** (at-least-once delivery ⇒ dedupe; e.g. `ReplacingMergeTree` keyed on `event_id`, or insert-if-absent). On ClickHouse-down, **nack/retry** — never ack-and-drop.
- **Schema `audit_events`** (append-only): `event_id`, `occurred_at`, `ingested_at`, `kind`, `correlation_id`, `trace_id`, `actor`, `actor_kind`, `role`, `element_id`, `pack_key`, `pack_version`, `decision`, `decided_by`, `sod_satisfied`, `schema_ref`, `authored_by_human`, `egress_host`, `egress_decision`, and a `payload` JSON column for kind-specific extras. **Reserve two nullable columns — `prev_hash`, `seal` — for the deferred hash-chain fast-follow: present in the schema, never populated in Phase B.** Retention via **TTL on `occurred_at`**, configurable, defaulting to a long audit horizon (multi-year), independent of the operational-trace TTL.
- **Read API** — `GET /audit/instances/{correlation_id}` → the instance's audit events in `occurred_at` order. This is the per-instance query foundation only; the decision-trail and lineage **read-models are Phase C**.
- Bootstrap `configure_telemetry("glea-service", …)` (it is a service too). Add it to compose with `OTEL_EXPORTER_OTLP_ENDPOINT`, the ClickHouse DSN, and the `amendia.events` connection.

### 4. Close the native-mode egress gap

Today `derive_egress_policy` is enforced only in the sandboxed executor; the in-process (native) path is fail-open (assessment gap).

- Instrument the **in-process executor / MCP-call path** to consult `derive_egress_policy(descriptor)` for the capability and check the **target host against the allowlist before the call**.
- **Record always**: set `amendia.egress.decision`/`amendia.egress.host` on the node span and publish `EgressDecisionEvent` on **deny** (allow may be sampled/optional to bound volume).
- **Enforce behind a setting** `NATIVE_EGRESS_ENFORCE` (default **on**): a denied host blocks the call with a clear error. **Verify** the derived allowlist admits every legitimate host in the existing `wire_transfer_exception` and `restaurant_dinein` capabilities — nothing legitimate may be denied. If correctness of the derivation is uncertain for any case, default that case to **audit-only** (record `deny`, do not block) and flag it, rather than break a real call.

## Constraints (hard)

- **Domain-neutral:** no pack/domain term in any event field, routing key, span attribute, or `audit_events` column. Review gate.
- **`glea-service` is the sole writer of `audit_events`.** Producers only publish to the exchange; nothing else writes the table.
- **No event loss:** durable named queue + idempotent (dedupe-by-`event_id`) writes + nack-on-ClickHouse-down. Fail-soft everywhere: broker or ClickHouse down must not break governed actions or request handling.
- **No hash-chain** in Phase B — schema-ready (`prev_hash`/`seal` columns) only.
- **Additive:** enriching existing events must keep current consumers (notification-service) working. Egress enforcement must not break legitimate calls.
- Out of scope (Phase C–E): rationale capture, decision-trail read-model, lineage projection API, aggregate tiles/SQL endpoints, frontend, hash-chain sealing, cross-instance console.

## Acceptance / exit criteria

1. A full **wire-repair** run lands append-only `audit_events` rows for: instance lifecycle (created/completed), **each HITL decide** (with `decided_by` + `sod_satisfied`), **each artifact commit** (`schema_ref` + `authored_by_human`), and **egress decisions** — every row carrying `correlation_id` + `trace_id` that **join to the Phase A `otel_traces` spans** for the same run (show the join).
2. **No-loss / idempotent:** with `glea-service` stopped, published events queue on its durable queue and are consumed on restart (nothing lost); redelivering the same `event_id` produces **no duplicate row**.
3. **Native egress:** a capability targeting an **undeclared** host is recorded `deny` (and blocked when `NATIVE_EGRESS_ENFORCE` is on); every legitimate host in the wire/restaurant capabilities is `allow` and unaffected.
4. **Cross-service governance:** an identity **role grant/revoke** and a registry **pack publish/deprecate/rollback** each land as `audit_events` rows. `GET /audit/instances/{correlation_id}` returns the ordered events for a run.
5. Domain-neutral (asserted); existing unit suites green (the integration e2e is deferred to the end-of-track full-stack run); ClickHouse-down and broker-down are fail-soft with **no event loss**.

## Working agreement

Supervised: you (CC) write the code; **propose up front** (a) the audit-event contract set + routing keys, (b) the `audit_events` ClickHouse schema (incl. the reserved `prev_hash`/`seal` columns), and (c) the `glea-service` layout, before large edits. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`). Do **not** run the full-stack e2e — that's a single end-of-track gate on the operator's side after all phases.
