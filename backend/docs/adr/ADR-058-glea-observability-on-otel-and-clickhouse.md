# ADR-058 — GLEA hardening: OpenTelemetry collection, a ClickHouse system-of-record, and a dedicated `glea-service`

**Status:** Accepted (2026-08-05)
**Related:** ADR-017 (OTLP `exec_meta` in nemoclaw), ADR-019 (egress policy / sandbox-creation-time enforcement), ADR-024 (self-descriptive endpoints), ADR-043 (compensation log), ADR-048 (capability input_map / dataflow), ADR-055 (deterministic four-eyes), the GLEA engineering assessment (`backend/docs/engineering/amendia_governance_lineage_explainability_audit_assessment.md`) and implementation plan (`backend/docs/engineering/amendia_glea_otel_implementation_plan.md`).

**Implementation status (2026-08-05):** Phases A–E implemented and validated end-to-end on a live stack (restaurant dine-in run `pi-79e3a7b3df78460d`): OTel traces + lineage, the `glea-service` audit system-of-record, the decision-trail / lineage / metrics / trace read-models, and the composed tabbed instance view all confirmed against real ClickHouse. Three live-surfaced fixes applied: glea ClickHouse client concurrency (single session → bounded pool), a missing `audit_events.artifact_key` column, and confirmation of the lineage `Links.SpanId` extraction. Outstanding (bundled fast-follow): config-forge `ConfigRefResolvedEvent` publisher, hash-chain sealing of `prev_hash`/`seal`, and a cosmetic lineage node dedupe; Phase D §3 scheduled-query alerting remains optional.

## Context

The GLEA assessment found Amendia's Governance, Lineage, Explainability & Audit **substrate** strong but its **surface and durability** weak. Concretely: the append-only `actor_log`, version-pinned `schema_ref`, `input_map` dataflow, and proposed-vs-approved HITL records already exist, but (a) there is **no durable, queryable audit store** — lifecycle events are published to RabbitMQ, delivered to notifications, and then dropped; (b) traces exist only in `nemoclaw` mode (`exec_meta` is omitted in native); (c) egress policy is enforced only in the sandboxed executor (native is fail-open); (d) none of it is surfaced beyond a dev/debug JSON endpoint; and (e) agent rationale is never captured.

We want one collection/reporting backbone rather than a bolt-on per pillar. OpenTelemetry is the natural choice: the OpenShell/NeMoClaw sandboxes already emit OTLP, and OTel gives a vendor-neutral wire format for the whole platform.

Two ingestion questions then arise. **Where is the system-of-record?** and **how do audit events reach it?** A telemetry backend (short-retention, sampled, not tamper-evident) cannot be the compliance record. And Amendia already has a first-class domain-event backbone on RabbitMQ — the same one `notification-service` consumes — which is a better carrier for governed business events than OTel logs, because a consumer that persists them can own append-only + ordering + integrity at write time.

## Decision

### 1. ClickHouse is the single telemetry backend and the audit system-of-record

All three signals land in **ClickHouse**: `otel_traces`, `otel_logs`, and a curated append-only `audit_events` table. There is **no Prometheus, Grafana, or Loki.** Metrics are **derived by SQL** over the traces and logs already stored (approval latency, decisions per role, SLA breaches, egress-denied counts, capability duration) and surfaced as tiles — not a separate metrics pipeline. If a pre-aggregated OTel metrics signal is ever needed, it exports into ClickHouse too, never Prometheus. Optional alerting is a scheduled ClickHouse query → the existing `notification-service`. Retention is per-table TTL (audit multi-year; operational traces 30–90 days), so trace volume never forces short audit retention. A read-only trace UI (Grafana/Jaeger over ClickHouse) may be attached later at zero code cost.

### 2. Hybrid ingestion — traces over OTLP, audit events over RabbitMQ

Two carriers, each the right tool for its signal:

- **Traces → OTLP → OTel Collector → ClickHouse.** Spans are OpenTelemetry-native and come from many services **and the sandboxes, which already emit OTLP**. Routing traces through RabbitMQ would re-invent OTLP transport and break sandbox-trace unification. So the Collector is the single aggregation point for traces (and any OTel logs), pointed at the same endpoint the sandboxes already use.
- **Audit / governance events → RabbitMQ → `glea-service` consumes → writes `audit_events`.** Governed business events (HITL claim/decide with `decided_by`+`sod_satisfied`, four-eyes enforcement, egress allow/deny, artifact commit, lifecycle transitions, and — from other services — role grant/revoke, pack publish/deprecate/rollback) are **domain events**, and Amendia already publishes lifecycle events to RabbitMQ. `glea-service` becomes another consumer of that backbone (alongside `notification-service`) and **persists** them. This is the design proposed in review, adopted here — it is strictly better than emitting these as OTel logs because the persisting consumer **owns the write**: append-only, per-`correlation_id` ordering, schema-validation, and hash-chain sealing all happen in one place, synchronously, at ingest. It also closes the assessment's core gap (events published but never persisted) precisely, and reuses at-least-once delivery, acks, and dead-lettering for compliance-critical events.

Both stores share `correlation_id` and `trace_id` (stamped into every published audit event), so the read-models join a run's audit events to its trace spans.

### 3. A dedicated, single-purpose `glea-service`

A new service at `backend/services/platform/glea-service`. It is **not** part of the runtime engine. It:

- **Consumes** the audit/governance events from RabbitMQ and **writes** the append-only `audit_events` table in ClickHouse — the sole writer of that table, owning integrity (append-only, per-`correlation_id` hash-chain, retention).
- **Reads** ClickHouse (`otel_traces`, `otel_logs`, `audit_events`) to serve the GLEA **read-models** to the webui: per-instance audit trail, decision trail (proposed-vs-approved with actor+role+timestamp+comment+SoD badge), lineage/dataflow graph (from `input_map` + span links), the instance trace tree, and the SQL-derived aggregate tiles.
- **Owns** audit-store maintenance (hash-chain sealing, retention verification) and the optional scheduled alerting queries.

`agent-runtime` keeps its existing live-instance API and gains **no ClickHouse dependency** — it emits OTLP (traces) and publishes audit events (RabbitMQ) like any other producer. This keeps the compliance surface decoupled from the execution engine, isolates the ClickHouse dependency in one thin read-mostly service, and is the seam the deferred cross-instance Governance & Audit console will plug into.

### 4. A shared `amendia_telemetry` library and domain-neutral conventions

A package sibling to `amendia_contracts`: OTel bootstrap (traces + logs), resource attributes, and helpers (`start_instance_trace`, `node_span`, `link_to_artifacts`, `audit_event`, `record_decision`). Every service imports it; none hand-rolls OTel. All attributes are **structural** — `amendia.correlation_id`, `amendia.process_instance_id`, `amendia.pack_key`/`pack_version`, `amendia.element_id`, `amendia.actor`/`actor_kind`, `amendia.role`, `amendia.artifact_key`/`schema_ref`, `amendia.decision`/`decided_by`, `amendia.sod_satisfied`, `amendia.execution_mode`/`simulation`, `amendia.egress.decision`/`host`, `amendia.rationale`. **No pack or domain term ever enters a span, log, event, or label.** The new audit-event contracts live in `amendia_contracts` (extending `process_events`/`hitl_events`), typed and versioned.

### 5. Traces carry explainability + lineage; the instance trace survives HITL waits

The instance's root `SpanContext` is persisted into the checkpoint `state.trace` (an existing field), so across HITL pauses and crash-recovery resumes every node span re-parents to the same root — a coherent execution tree even for multi-day instances. **Lineage rides on span links:** because `input_map` already declares each input's source, each node span links to the span(s) that produced its inputs. Adopting the OTel SDK **in-process** also gives native mode real spans (parity with nemoclaw — closing the `exec_meta`-only gap), and Phase B instruments the in-process executor to **enforce** the derived egress allowlist (closing the native fail-open gap), recording `amendia.egress.decision` either way. Deep-agent/LLM capabilities record `amendia.rationale`.

### 6. Frontend: upgrade the per-instance view (no cross-instance console yet)

`webui/features/instances/InstanceDetailPage.tsx` composes two sources — `agent-runtime` for live state (step tracker, status) and `glea-service` for the GLEA read-models — adding a decision trail (reusing `CorrectionDiff`), lineage graph, in-view trace tree, per-instance audit events, and aggregate tiles. The cross-instance console (global audit search, SoD reports, auditor export) is deferred; Phase B's queryable store is its foundation.

## Phasing

- **A — Telemetry foundation.** `amendia_telemetry`; SDK bootstrap across services; Collector + ClickHouse in compose; unify sandbox OTLP; instance root-span persistence + node spans + input-artifact links; native+nemoclaw parity.
- **B — Audit system-of-record + governance.** Audit-event contracts; `glea-service` RabbitMQ consumer + `audit_events` writer (append-only, per-correlation hash-chain, TTL); close native egress enforcement; per-instance audit query API.
- **C — Explainability enrichment.** Agent-rationale capture; decision-trail + lineage read-models.
- **D — Derived tiles.** SQL aggregate endpoints + optional scheduled-query alerting via `notification-service`.
- **E — Frontend.** Upgrade the instance view.

## Consequences

- **+** One durable, queryable, append-only, hash-chainable audit system-of-record — the assessment's top gap closed, precisely, by persisting the events Amendia already publishes.
- **+** Governance closed on both fronts: native mode gets real traces and enforced egress.
- **+** Explainability and lineage become product surfaces, not a debug endpoint; agent rationale is captured.
- **+** One new backend dependency (ClickHouse) and one thin new service; the compliance surface is decoupled from the engine and ready for a future cross-instance console.
- **+** Reuses the existing RabbitMQ event backbone and `notification-service`; audit integrity is owned at a single write point.
- **−** Two ingestion paths (OTLP for traces, RabbitMQ for audit events) — more moving parts, but each is the correct carrier; they are joined by `correlation_id`/`trace_id`.
- **−** Per-`correlation_id` ordering for the hash-chain needs care if `glea-service` is replicated (single consumer, partition by `correlation_id`, or periodic ordered sealing).
- **−** Instrumentation touches every service; done via one shared library to bound the blast radius, additive and side-effect-free w.r.t. graph execution.

## Non-goals

- No Prometheus / Grafana / Loki; no separate metrics pipeline (derive by SQL).
- No cross-instance Governance & Audit console this cycle (deferred; foundation laid in Phase B).
- No change to BPMN semantics or the execution engine's control flow — instrumentation only; the sole new state field (`state.trace` root-span context) is optional (absent → new trace, never a crash), mirroring ADR-017's native-parity discipline.
- Amendia does not mandate a specific external trace UI; ClickHouse is the store, any OTLP/SQL-compatible tool can attach read-only later.
