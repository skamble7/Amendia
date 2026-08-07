# Amendia GLEA Hardening — OpenTelemetry-Backed Implementation Plan

> **STATUS: DELIVERED (2026-08-05).** ADR-058 is Accepted and Phases A–E + the fast-follow bundle are implemented and validated end-to-end. See **[Implementation status — DELIVERED](#implementation-status--delivered-adr-058-accepted-2026-08-05)** at the end for the as-built record; the planning tense below is preserved as the design record.


_Closing the Governance, Lineage, Explainability & Audit gaps identified in the engineering assessment, on an OpenTelemetry collection backbone. This is the basis for **ADR-058** and the phased CC prompts that follow it._

## Decisions locked this session

| Decision | Choice | Notes |
|---|---|---|
| Audit system-of-record | **Dedicated durable store** (not a telemetry backend) | ClickHouse |
| Telemetry backend | **ClickHouse — single backend** | Traces + logs + audit; metrics derived by SQL over the same store |
| Prometheus / Grafana / Loki | **Not used** | See rationale below — ClickHouse + the upgraded Amendia view cover the need |
| OTel signals | **Traces + Logs now** (system-of-record); metrics **derived by SQL**, not a separate pipeline | Dedicated OTel metrics export optional later (also into ClickHouse) |
| Frontend scope | **Upgrade the per-instance view** | Renders decision trail, lineage, audit, and aggregate tiles from ClickHouse read-models. No cross-instance console this phase |

**Why no Prometheus, Grafana, or Loki.** With ClickHouse as the system-of-record and the Amendia webui as the product surface, none of the three earns its keep now:

- **Loki** — never needed; logs land in ClickHouse (Loki is Grafana's *alternative* log store).
- **Grafana** — only a visualization layer. Its two jobs here (metric dashboards; raw trace-waterfall UI) are covered by the upgraded Amendia view and, for engineer trace exploration, can be added later by pointing Grafana/Jaeger at ClickHouse read-only — **zero code cost, no rework**.
- **Prometheus** — its value is operational metrics + alerting. But the metrics we care about (approval latency, decisions per role, SLA breaches, egress-denied counts, capability exec duration) are all **derivable as SQL aggregations over the traces + logs already in ClickHouse**, surfaced as tiles in the Amendia view. If a pre-aggregated OTel metrics signal is ever wanted, the Collector's ClickHouse exporter accepts metrics too — still no Prometheus.

**The one trade-off — push alerting.** Prometheus/Alertmanager would proactively fire on, e.g., an egress-denial spike. Without it, the path is a **scheduled ClickHouse query → the existing notification-service** (Slack/Teams/email) — reusing infrastructure Amendia already has, staying domain-neutral. Add Prometheus later only if operational alerting outgrows scheduled queries.

**Net:** ClickHouse is the **single new dependency** — one store to operate, secure, back up, and apply retention/TTL to.

## Target architecture

```
 Amendia services (agent-runtime, process-registry, identity,
 notification-service, ingestor, config-forge)  ──┐
                                                   │  OTLP (traces + logs)
 OpenShell / NeMoClaw sandboxes (already OTLP) ────┤
                                                   ▼
                                        ┌────────────────────┐
                                        │  OTel Collector    │  (gateway; reference config)
                                        └─────────┬──────────┘
                             traces + logs + audit│
                                                  ▼
                                        ┌────────────────────┐
                                        │     ClickHouse     │  single backend / system-of-record
                                        │  traces·logs·audit │  (metrics derived by SQL)
                                        └─────────┬──────────┘
                                                  │ read-model APIs
                                                  ▼
                              ┌─────────────────────────────────────┐
                              │  Amendia webui (upgraded instance    │
                              │  view): decision trail · lineage ·   │
                              │  audit · aggregate tiles · trace tree │
                              └─────────────────────────────────────┘

  Alerting (optional): scheduled ClickHouse query → existing notification-service
  Later, zero-cost: attach Grafana/Jaeger read-only to ClickHouse for engineer trace waterfalls
```

Every Amendia service becomes an OTel producer through one shared bootstrap package. The Collector is the single aggregation point — critically, the OTLP that OpenShell/NeMoClaw already emit is pointed at the **same** Collector, so a sandboxed capability's trace stops being an opaque `exec_meta` id and becomes a real span linked into the instance's trace.

### Domain-neutral semantic conventions

A single Amendia attribute namespace, all structural — **no domain terms** (nothing about wires, restaurants, parties, etc.), preserving domain-neutrality:

| Attribute | Meaning |
|---|---|
| `amendia.correlation_id` | Instance correlation key — the spine of every trace/log/audit row |
| `amendia.process_instance_id` | Instance id |
| `amendia.pack_key` / `amendia.pack_version` | Which immutable pack version ran |
| `amendia.element_id` | BPMN element |
| `amendia.actor` / `amendia.actor_kind` | Capability id or user id; `capability` \| `human` \| `timer` |
| `amendia.role` | Role that acted/approved (governance) |
| `amendia.artifact_key` / `amendia.schema_ref` | Pinned artifact identity (lineage) |
| `amendia.decision` / `amendia.decided_by` | HITL outcome + approver (explainability/governance) |
| `amendia.sod_satisfied` | Four-eyes check result |
| `amendia.execution_mode` / `amendia.simulation` | native \| nemoclaw; sim flag |
| `amendia.egress.decision` / `amendia.egress.host` | Egress allow/deny (governance) |

These map cleanly onto the existing `actor_entry`, `input_map`, `schema_ref`, and HITL-decision fields — instrumentation reads data that already exists.

### How each signal maps to a GLEA pillar

- **Traces → Explainability + Lineage.** One trace per instance. The instance's root `SpanContext` is persisted into the checkpoint `state.trace` (which already exists) so that across HITL waits and crash-recovery resumes, every node span re-parents to the same root — giving a coherent execution tree even for processes that pause for days. **Lineage rides on span links:** because `input_map` already declares which upstream artifact feeds each input, each node span emits a span *link* to the span(s) that produced its inputs. The dataflow graph becomes navigable telemetry, and the same data backs the product lineage view.
- **Logs → Audit + Governance.** Structured OTel **log records** are emitted at each *governed decision point* (not reconstructed after the fact): HITL claim/decide with `decided_by` + `sod_satisfied`, four-eyes enforcement, egress allow/deny, artifact commit with `schema_ref` + `authored_by_human`, and lifecycle transitions. These flow to ClickHouse as the append-only `audit_events` system-of-record.
- **Metrics → derived, not a separate pipeline.** The operational figures (approval latency, decisions per role, SLA breaches, egress-denied counts, capability exec duration) are computed as SQL aggregations over the traces + logs already in ClickHouse and surfaced as tiles in the Amendia view (see Phase D). No dedicated OTel metrics export or Prometheus is required now; it can be added later (also into ClickHouse) if pre-aggregation is ever wanted.

### Gap-closure mapping

| Assessment gap | Closed by |
|---|---|
| Native mode has no trace (`exec_meta` omitted) | OTel SDK runs in-process → native capabilities emit real spans (parity) |
| Egress enforced in nemoclaw only (native fail-open) | Phase B instruments the in-process executor to consult `derive_egress_policy` and enforce (or audit+alert), with a `amendia.egress.decision` audit log either way |
| Agent reasoning not captured | Phase C adds `amendia.rationale` span attribute + persists it into `actor_log` meta for deep-agent/LLM capabilities |
| Lineage recorded but not surfaced | Span links + a lineage projection API + rendered graph in the instance view |
| Events ephemeral / no audit store | ClickHouse `audit_events` as append-only SoR with TTL + hash-chain |
| No cross-instance audit query | Foundation laid in Phase B (queryable store); full console is a later phase (out of scope now) |

## What changes, by component

**New shared package `amendia_telemetry`** (sibling to `amendia_contracts`): OTel bootstrap for traces + logs, the resource + semantic-convention definitions above, and thin helpers — `start_instance_trace(correlation_id, ...)`, `node_span(element_id, actor, ...)`, `link_to_artifacts(input_map)`, `audit_event(kind, **attrs)`, `record_decision(...)`. Every service imports this; no service hand-rolls OTel. Domain-neutral by construction.

**agent-runtime** — the deepest instrumentation: persist/restore the instance root span context in `state.trace`; wrap each node execution (`task_runner`) in a span with input-artifact links; emit audit logs from `hitl_service.decide`/`claim`, the egress path, and `_commit`; add native-mode egress enforcement in the in-process executor; populate rationale for deep-agent capabilities. Point OpenShell/NeMoClaw OTLP at the shared Collector.

**process-registry, identity, notification-service, ingestor, config-forge** — bootstrap the SDK; emit audit logs for their governed actions (role grant/revoke and admin-protection outcomes in identity; pack publish/deprecate/rollback in registry; config/credential-ref resolution in config-forge). notification-service keeps routing RabbitMQ events for notifications — audit no longer depends on it.

**Infra** — OTel Collector + ClickHouse added to compose with reference configs (no Prometheus/Grafana/Loki); ClickHouse schema (`otel_traces`, `otel_logs`, curated `audit_events`), per-table retention TTLs (e.g. audit multi-year, operational traces 30–90 days), and a hash-chain sealing mechanism per `correlation_id`. Optional alerting is a scheduled ClickHouse query → the existing notification-service.

**webui** — upgrade `features/instances/InstanceDetailPage.tsx` (details in the frontend section).

## Phased delivery

**Phase A — Telemetry foundation.** `amendia_telemetry` package; SDK bootstrap across all services; Collector + ClickHouse in compose; unify OpenShell/NeMoClaw OTLP into the Collector; instance root-span persistence + node spans + input-artifact span links; native+nemoclaw parity. _Exit: a full wire-repair run produces one coherent trace in ClickHouse spanning engine + sandbox spans, with lineage links, in both execution modes._

**Phase B — Audit system-of-record + governance.** Emit governed-decision OTel logs at all decision points; ClickHouse `audit_events` schema + retention TTL + per-correlation hash-chain; close the native-mode egress gap (enforce or audit+alert); per-instance audit query API. _Exit: every four-eyes decision, egress decision, and lifecycle transition of a run is an append-only, hash-linked row queryable by `correlation_id`; native egress violations are recorded/blocked._

**Phase C — Explainability enrichment.** Agent-rationale capture (span attr + `actor_log` meta) for deep-agent/LLM capabilities; decision-trail read model (proposed-vs-approved with actor+role+timestamp+comment+SoD badge); lineage projection API over `input_map`. _Exit: the API can return, per instance, an ordered decision trail and an artifact dataflow graph — no engine changes required to read them._

**Phase D — Aggregate read-models + tiles (ClickHouse SQL, no Prometheus/Grafana).** Expose a small set of aggregate query endpoints over the traces + logs in ClickHouse and render them as tiles in the Amendia view. Each is a SQL aggregation over data the earlier phases already persist — no separate metrics pipeline.

| Figure | Derived from (ClickHouse) | Pillar |
|---|---|---|
| Instances by outcome | lifecycle audit rows | audit/ops |
| HITL decisions by decision + role | decision audit rows | governance |
| Approval latency (p50/p95) | decide_at − task_created_at | governance/SLA |
| SLA breaches | timer/expiry audit rows | SLA |
| Capability exec duration (p50/p95) | span durations | ops |
| Egress-denied count | `amendia.egress.decision=deny` rows | governance |
| Four-eyes enforced count | `amendia.sod_satisfied` rows | governance |

_Optional alerting:_ a scheduled job runs the governance-relevant queries (e.g. egress-deny rate, SLA-breach storm) and pushes through the existing notification-service when a threshold trips.

**Phase E — Frontend upgrade (instance view).** See below.

_Out of scope now (later phase): the cross-instance Governance & Audit console — global audit search, SoD/four-eyes reports, auditor export. Phase B's queryable store is its foundation._

## Frontend upgrade — `InstanceDetailPage.tsx`

Building on what the current view already shows (step tracker, actor log, artifacts incl. Repair Draft vs Repair Approved, checkpoints):

- **Decision trail** (new section): per gate, the proposed → approved delta reusing the existing `CorrectionDiff.tsx`, with approver name + role + timestamp + comment and a "Four-eyes ✓" badge (from `amendia.sod_satisfied`). Formalizes what the Repair Draft/Repair Approved cards hint at today.
- **Actor log** enrichment: show role for human entries, add each entry's rationale (Phase C), and a "View trace" deep-link to the span for that step.
- **Lineage graph** (new): a rendered dataflow of artifacts — what fed what — from the projection API.
- **Trace view**: render the instance's span tree (execution waterfall) directly in the Amendia view from the ClickHouse trace read-model — no external trace UI needed. (Grafana/Jaeger can be attached read-only to ClickHouse later for engineers who want a richer waterfall, at zero code cost.)
- **Audit (per-instance)**: the append-only audit events for this instance from the store; make the "Checkpoints — 5 recorded transitions" line reference real audit rows rather than an engine-internal count.
- **Aggregate tiles**: the Phase D figures, scoped to this instance where meaningful (e.g. its approval latency, four-eyes badges).

## Guardrails

**Domain-neutrality:** all telemetry attributes are structural (`amendia.*` above); no pack/domain term ever enters a span or log. This is a review gate on every CC prompt in this track.

**No engine-semantics drift:** instrumentation is additive and side-effect-free with respect to graph execution — spans/logs wrap existing nodes; the persisted root span context is the only new state field, and it is optional (absent → a new trace, never a crash), mirroring the `exec_meta`-omitted-in-native discipline from ADR-017.

**Audit integrity:** `audit_events` is append-only; the hash-chain is per `correlation_id`; retention TTLs differ by table so operational trace volume never forces short audit retention.

## Open decisions to confirm before ADR-058 is finalized

1. **Hash-chain now or fast-follow?** Full tamper-evidence (per-instance hash-chain + periodic sealing) can land in Phase B or be stubbed (append-only + TTL now, chaining next). Recommendation: schema-ready in B, chaining enabled end of B.
2. **Dedicated metrics signal later?** Metrics are derived by SQL over ClickHouse for now. If pre-aggregated OTel metrics are ever wanted (very high volume, cheap high-frequency tiles), add the OTel metrics signal exporting *into ClickHouse* — still no Prometheus. Recommendation: derive-by-SQL until volume proves otherwise.
3. **Trace lifetime for very long-lived instances.** Persisted root-span context handles pauses, but a multi-week instance yields a very long trace; acceptable for v1, revisit if it strains the backend.

## Next steps

1. Turn this into **ADR-058 — GLEA hardening on an OpenTelemetry backbone** (written to `backend/docs/adr/`).
2. Produce the phased CC prompts (A→E), each self-contained with exit criteria and the domain-neutrality guardrail baked in.
3. Land Phase A first (telemetry foundation) and validate against a wire-repair run before moving on.

---

## Implementation status — DELIVERED (ADR-058 Accepted 2026-08-05)

This plan is fully implemented. **ADR-058 is Accepted**; Phases A–E plus a fast-follow bundle landed and were validated end-to-end against live wire-repair and restaurant dine-in runs. This section is the as-built record and supersedes the "Open decisions to confirm" and "Next steps" sections above.

### Delivered, by phase

- **A — Telemetry foundation.** `libs/amendia_telemetry` (shared bootstrap + the `amendia.*` conventions + instance-trace helpers). OTLP/HTTP → OTel Collector → ClickHouse `otel_traces`. The instance root `SpanContext` is persisted in `state.trace["otel"]` and restored across HITL waits and crash-recovery resumes, so every node span re-parents to one root. **Every** node factory is span-wrapped — task, MI iteration/join, call-activity, compensation, and control/routing nodes — with input-artifact **span links** as the lineage edges, including the MI-join fan-in (aggregate links back to every per-iteration producer). Native + nemoclaw parity; the real out-of-process capability-worker bootstraps its own provider and unifies its span into the instance trace.
- **B — Audit system-of-record + governance.** New **`glea-service`** consumes the durable `amendia.events` RabbitMQ exchange on its own named (competing-consumers) queue and is the **sole writer** of ClickHouse **`audit_events`** (ReplacingMergeTree, idempotent by `event_id`, multi-year TTL, reserved `prev_hash`/`seal`). Lifecycle + `HitlTaskDecided` events were enriched (decision/decided_by/role/sod_satisfied) and new governance events added — `EgressDecisionEvent`, `ArtifactCommittedEvent`, `RoleChangedEvent`, `PackLifecycleEvent`. **Native-mode egress enforcement** landed (`NATIVE_EGRESS_ENFORCE`, default on), closing the fail-open gap.
- **C — Explainability.** A bounded `amendia.rationale` (~1.2 KB cap) is captured for deep-agent/LLM capabilities onto the span and the actor-log entry meta — never fabricated for plain MCP tools. Decision-trail read-model (ordered gates with proposed→approved artifact refs + decided_by/role/sod/comment) and the lineage projection API (span-link graph → artifact DAG, MI fan-in preserved).
- **D — Aggregate read-models.** A per-instance metrics bundle plus a platform-wide window, every figure a **SQL aggregation over ClickHouse** — no metrics pipeline, no Prometheus.
- **E — Frontend.** The instance view was rebuilt as a tabbed surface (**Overview / Artifacts / Governance / Observability**) composing agent-runtime (live state + artifact values) with the glea read-models: decision trail via the existing `CorrectionDiff` + a four-eyes badge, actor-log enriched with role + rationale + a "view trace" affordance, the lineage DAG, an in-view trace waterfall, per-instance audit events with an honest checkpoints line, and the metric tiles. Every GLEA section degrades gracefully when `glea-service` is absent (no blank page, no crash).
- **Fast-follow bundle.** config-forge `ConfigRefResolvedEvent` publisher (emits which ref + resolved-or-not, **never the resolved value**, fail-soft); **hash-chain sealing** (per-`correlation_id` `prev_hash`/`seal`, a background sealer loop, and a `GET /audit/instances/{cid}/seal` verification endpoint); lineage node dedupe that preserves MI producers.

### As-built refinements vs. the plan above

- **Audit rides the RabbitMQ backbone, not the OTel logs signal.** The plan framed audit as OTel *log records* → ClickHouse. As built, governed events travel the existing **`amendia.events`** topic exchange to `glea-service`, the sole writer of `audit_events`. Traces still flow OTLP → Collector → `otel_traces`; the two join on `correlation_id` + `trace_id`. (A logs provider is wired and fail-soft in `amendia_telemetry`, but it is not the audit path.)
- **Metrics are SQL-derived — there are no OTel meters.** No `Meter` / counter / histogram / gauge instruments were defined anywhere. Every operational figure is a ClickHouse aggregation exposed by `glea-service`. This is the deliberate ADR-058 choice; a dedicated OTel metrics signal remains a "later, into ClickHouse" option only.

### Read-model API surface (`glea-service`, prefix `/audit`)

`GET /audit/instances/{correlation_id}` · `…/decision-trail` · `…/lineage` · `…/trace` · `…/metrics` · `…/seal`, and the platform-wide `GET /audit/metrics?since=…&until=…`. The per-instance **metrics bundle** returns: `approval_latency_ms{p50,p95,count}`, `capability_duration_ms{p50,p95,count}`, `hitl_decisions[{decision,role,count}]`, `four_eyes_enforced`, `egress_denied`, `sla_breaches`; the platform-wide window adds `instances_by_outcome{completed,failed}`.

### Open decisions — resolved

1. **Hash-chain now or fast-follow?** → **Delivered in the fast-follow.** Schema-ready in B (`prev_hash`/`seal`); chaining + a background sealer + the `/seal` verification endpoint landed after Phase E.
2. **Dedicated metrics signal later?** → **Held: derive-by-SQL.** No OTel metric instruments; revisit only if volume demands pre-aggregation (still into ClickHouse, still no Prometheus).
3. **Trace lifetime for long-lived instances** → **Accepted for v1.** Root-span persistence handles multi-day pauses; unchanged.

### Still deferred (explicitly out of scope; foundations in place)

- The **cross-instance Governance & Audit console** (global audit search, SoD/four-eyes reports, auditor export) — `GET /audit/metrics` is its foundation.
- **Push alerting** (Phase D §3) — not built; the intended path remains a scheduled ClickHouse query → the existing notification-service.
