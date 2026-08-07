# Amendia: Governance, Lineage, Explainability & Audit — Where We Stand

> **STATUS: this is the BASELINE assessment (starting point). The gaps below were subsequently closed by ADR-058 (delivered 2026-08-05).** See **[Update — where we landed: GLEA gaps closed](#update--where-we-landed-glea-gaps-closed-adr-058-delivered-2026-08-05)** at the end for the as-built state, refreshed scorecard, and telemetry reference.


_Investigation of the actual implementation across `agent-runtime`, `process-registry`, `platform/identity`, and `platform/notification-service`. Assessed against what is built, what is partial, and what is missing — not inferred from ADR titles._

## TL;DR

Amendia already has an unusually strong **substrate** for all four pillars because they fall out of the execution model rather than being bolted on: a typed, version-pinned artifact dataflow (lineage), an append-only `actor_log` persisted at every checkpoint boundary (explainability + audit), and deterministic HITL/SoD gates enforced at runtime (governance). The honest gap is at the **surface and the durability layer**: the raw material exists but is exposed only as a dev/debug endpoint, there is no assembled lineage/explanation view, egress governance is enforced in `nemoclaw` mode only, and there is no first-class, immutable, queryable audit store — audit today is a *byproduct* of LangGraph checkpoint state, not a subsystem.

Overall maturity: **Governance — strong. Lineage — strong substrate, no surfaced view. Explainability — good raw material, no product surface, thin on agent rationale. Audit — partial; de-facto only.**

---

## 1. Governance — _who may do what, and which controls are enforced_

**Built and enforced at runtime.**

- **HITL decision lifecycle** (`agent-runtime/app/services/hitl_service.py`): strict `open → claimed → decided` with CAS transitions. Claim requires the task's required role ∈ the caller's roles. Decide checks the task is CLAIMED and the assignee matches. An allowed-decisions table constrains what each gate can return.
- **Four-eyes / Separation of Duties**: `_check_sod` runs at **both** claim and decide, keyed by `amendia_user_id`, so the same human cannot both propose and approve. This is backed by ADR-055's deterministic gate synthesis — the four-eyes gate `(H, S, D)` is formed structurally from SoD pairs + the guaranteed predecessor, not left to the LLM. This is the strongest governance guarantee in the platform.
- **Identity governance** (`platform/identity/app/services/guardrails.py`): admin self-protection (can't strip your own `role.platform.admin`), last-admin protection (can't revoke the final admin — re-checked at write time to defeat racing requests). Role assignment is the governance root of the SoD/HITL model.
- **Egress / tool policy** (`agent-runtime/app/engine/executor/policy.py`): `derive_egress_policy` builds a per-capability allowlist **purely from declared contract data** — the MCP `runtime.endpoint` host, or `inference.local` for LLM. This is genuinely domain-neutral: no hardcoded destinations.
- **Config/credential governance**: LLM access is brokered through ConfigForge (`LLM_CONFIG_REF`) and, in sandboxed mode, credentials are brokered at the gateway rather than handed to capability code.

**Gap — egress is derived everywhere but enforced in one mode only.** `derive_egress_policy` is imported and applied **only** in `sandboxed.py` (nemoclaw path), passed as `egress_policy` at sandbox-creation time. The native `InProcessExecutor` path (`core.py` / `dispatch.py`) does **not** consult or enforce the policy — native mode is fail-open on egress. The allowlist is computed but nothing stops an in-process capability from talking to an undeclared host. This is acceptable for dev/native but must be labeled clearly: **egress governance is a nemoclaw-only guarantee today.**

**Gap — "policy engine" is contract-derivation, not a rule engine.** There is no standalone policy service with authored rules, versioning, or a decision log. Governance is expressed as (a) role membership, (b) SoD exclusions, (c) contract-derived egress. That's coherent and domain-neutral, but if a customer asks "show me the policy that governed this step and who authored it," we can point to the pack + roles, not to an evaluable, audited policy object.

---

## 2. Lineage — _provenance of every artifact and input_

**Strong substrate; reconstructable, not surfaced.**

- **Typed, version-pinned artifacts** (`task_runner.py`): every artifact carries a `schema_ref` pinned to `art.key@x.y.z` — an immutable schema version. Instances are pinned to immutable pack versions (ADR-056), so an artifact always resolves to the exact schema that produced it, even after the pack is edited.
- **Explicit dataflow via `input_map`** (ADR-048): each capability input is resolved by `_resolve_source` from the envelope or a specific upstream artifact/field. The `input_map` **is** the dataflow graph — it declares, per binding, exactly which upstream output feeds each input (including nested `fields`). This is real lineage wiring, not inference.
- **Human vs machine provenance**: human-authored artifacts are tagged (`authored_by_human`), and gate artifacts carry the `proposed_actions` the agent suggested alongside the human's decision.
- **Reverse lineage for undo**: the append-only `compensation_log` (ADR-043) snapshots each committed side-effect `{activity_id, handler_id, scope, snapshot, at}` so compensation can walk it LIFO.

**Gap — no assembled lineage view.** Everything needed to answer "trace `art.wirefix_mcp.resolution` back through every input, capability, and human that touched it" is present in `input_map` + `actor_log` + pinned `schema_ref`, but nothing **projects** it into a graph or timeline. It is reconstructable by a query we haven't written, not a feature we expose. For a governance/compliance buyer, lineage is only real once it's rendered.

---

## 3. Explainability — _why the process did what it did_

**Good raw material; no product surface; thin on agent rationale.**

- **`actor_log`** (`agent-runtime/app/engine/state.py`): append-only (`operator.add`), one entry per node commit — `{element_id, actor, kind ∈ {capability, human}, at, exec_meta?}`. The module docstring states the intent plainly: *"that checkpoint trail is the audit record."* It is persisted by the Mongo checkpointer at every node boundary.
- **Proposed-vs-approved delta**: the single most valuable explainability signal for an agentic platform is captured. The gate artifact holds `proposed_actions`; the HITL decision records `decision`, `decided_by`, `edits`, `approved_action_ids`, and `comment`. So "the AI proposed X, the human changed it to Y and approved" is fully recoverable.
- **Distributed-trace hooks**: in `nemoclaw` mode the sandbox's OTLP `exec_meta` (trace id, tagged to the `element_id`) attaches to the `actor_log` entry, linking a capability execution to an external trace.
- **Correlation**: every event and state carries a `correlation_id` (+ `causation_id`), threading a run together.
- **Debug surface**: `instances.py` exposes `GET /{id}` (returns `actor_log`) and a flag-guarded `GET /{id}/state` (full checkpoint state incl. `trace`).

**Gap — native mode has no trace.** `exec_meta` is omitted entirely in native mode (by design, for byte-for-byte parity per ADR-017). So OTLP-grade explainability only exists under nemoclaw.

**Gap — no agent reasoning captured.** The `actor_log` records *that* a capability ran and *when*, plus a trace id — not *why* the agent chose what it did. For deep-agent capabilities, the LLM's rationale/plan is not persisted into the explainability record. "Why did the agent draft this repair?" is not answerable from the log today.

**Gap — no human-facing explanation.** What exists is a JSON debug endpoint, not a rendered timeline/decision-trail a business user or auditor would read. Explainability is currently an engineering artifact.

---

## 4. Audit — _durable, queryable, tamper-evident record_

**Partial — a de-facto trail, not a subsystem.**

- **What is durable**: the LangGraph Mongo checkpointer persists full state (`actor_log`, `artifacts`, `compensation_log`, …) at every node boundary into `lg_checkpoints` / `lg_checkpoint_writes`, and LangGraph retains checkpoint history (the writes collection), so a per-instance replayable trail exists. The `actor_log` and `compensation_log` are append-only *within* state, so they don't lose history across a run.
- **Event stream**: lifecycle events (`ProcessCompleted/Failed`, `HitlTaskCreated/Expired`, `TimerFired`, `MessageReceived`) are published to RabbitMQ and consumed by `notification-service`, which maps them to signals (Slack/Teams/email).

**Gap — events are ephemeral.** `notification-service`'s consumer routes events to notifications; it does **not** persist them. There is no `event_store` / `audit_log` collection anywhere (searched all services — none). Once delivered, the event is gone. The durable record is the checkpoint, which is runtime-private (`# runtime-private` in config) and shaped for engine replay, not for audit query.

**Gap — no audit primitives.** No retention/TTL policy, no tamper-evidence (hashing/signing/append-only ledger semantics beyond Mongo's mutability), no export or audit-report API, no cross-instance audit query ("show every four-eyes approval by user U last quarter"). The checkpoint tables are LangGraph-internal; we'd be reverse-engineering an implementation detail to audit against them.

---

## Scorecard

| Pillar | Substrate | Enforcement | Surfaced to users | Verdict |
|---|---|---|---|---|
| **Governance** | Strong (roles, SoD, contract-derived egress) | Strong for HITL/SoD; egress **nemoclaw-only** | Admin UI for roles; no policy-decision log | **Strong, one enforcement gap** |
| **Lineage** | Strong (pinned `schema_ref` + `input_map` + `compensation_log`) | N/A (structural) | **None** — reconstructable, not projected | **Strong substrate, no view** |
| **Explainability** | Good (`actor_log`, proposed-vs-approved, OTLP hooks) | N/A | Debug JSON only; no agent rationale | **Good material, no surface** |
| **Audit** | Partial (checkpoint trail only) | N/A | None; events not persisted | **Partial / de-facto** |

---

## Recommended next moves (in priority order)

1. **First-class audit store.** Add a durable, append-only audit projection — a consumer that persists the lifecycle event stream **and** materializes `actor_log`/HITL-decision/compensation records into an `audit_log` collection keyed by `correlation_id`, independent of the LangGraph checkpoint tables. This is the biggest gap and unblocks everything below. Domain-neutral: it records element ids, actors, roles, schema refs — no domain terms.
2. **Lineage & explanation projection API.** A read model that walks `input_map` + `actor_log` + pinned `schema_ref` to return, per instance, (a) the artifact dependency graph and (b) the ordered decision trail with proposed-vs-approved deltas. This turns existing substrate into a real feature with no engine changes.
3. **Close the native-mode egress gap** — or explicitly document it as a non-guarantee. At minimum, log a warning when a native capability would violate its derived allowlist; ideally enforce it in the in-process path too.
4. **Capture agent rationale.** Extend `exec_meta` (or a sibling field) so deep-agent capabilities can persist a short rationale/plan into the `actor_log`, and make it available in native mode (not only via OTLP under nemoclaw).
5. **Audit query + export surface.** Cross-instance queries and an export/report endpoint on top of (1), plus a retention policy and optional hash-chaining for tamper-evidence.

Items 1 and 2 are the highest leverage: most of the hard modeling work (typed pinned artifacts, `input_map`, `actor_log`, proposed-vs-approved) is already done — what's missing is a durable projection and a view over it.

---

## Update — where we landed: GLEA gaps closed (ADR-058, delivered 2026-08-05)

_The assessment above is the **baseline** (the starting point that justified the work). Everything below is the **as-built** result. ADR-058 ("GLEA observability on OpenTelemetry + ClickHouse") is **Accepted**; Phases A–E plus a fast-follow bundle landed and were validated end-to-end on live wire-repair and restaurant dine-in runs. Read the two together as before → after._

**The architecture that closed the gaps.** One shared `libs/amendia_telemetry` bootstrap makes every service an OTel producer. **Traces** flow OTLP/HTTP → OTel Collector → ClickHouse `otel_traces` (one coherent trace per instance; the root `SpanContext` is persisted in `state.trace["otel"]` and restored across HITL waits and resumes). **Audit** travels the existing `amendia.events` RabbitMQ exchange to a new read-only **`glea-service`**, the **sole writer** of the append-only ClickHouse **`audit_events`** table; traces and audit rows join on `correlation_id` + `trace_id`. **Metrics are derived by SQL** over those two tables — there is no metrics pipeline and no Prometheus/Grafana/Loki.

### Pillar-by-pillar closure

**Governance — the one enforcement gap is closed.** Native-mode egress is now enforced: the in-process executor consults `derive_egress_policy` and blocks calls to undeclared hosts under `NATIVE_EGRESS_ENFORCE` (default on), recording `amendia.egress.decision`/`host` on the span and publishing an `EgressDecisionEvent` on deny. Egress governance is no longer a nemoclaw-only guarantee. Role grants/revokes and pack publish/deprecate/rollback now emit `RoleChangedEvent`/`PackLifecycleEvent` audit rows. _(Still open: a standalone authored **policy rulebook** object — governance is still expressed as roles + SoD + contract-derived egress, now fully audited but not a separately versioned policy document.)_

**Lineage — now surfaced, not just reconstructable.** The `input_map` dataflow is emitted as **span links** on every node span (Phase A wraps every node factory, so there are no gaps and no dangling producers — including the MI-join fan-in). `glea-service` projects those links into an artifact **DAG** (`GET /audit/instances/{cid}/lineage`), and the instance view renders it as a graph. The chain from raw input to final outcome is now a feature, not a query we hadn't written.

**Explainability — real product surface + agent rationale.** Deep-agent/LLM capabilities now capture a bounded `amendia.rationale` (~1.2 KB cap) onto the span **and** the actor-log entry meta — never fabricated for plain MCP tools. The **decision-trail** read-model returns the ordered gates with proposed→approved artifact refs, `decided_by`, `role`, `sod_satisfied`, and comment; the instance view renders it with the existing `CorrectionDiff` and a **"Four-eyes ✓" badge**, plus an in-view **trace waterfall**. Native mode now emits real spans too (parity), so explainability no longer depends on nemoclaw.

**Audit — a first-class, immutable, queryable subsystem.** `audit_events` is an append-only ClickHouse table (ReplacingMergeTree, idempotent by `event_id`, multi-year TTL independent of the operational-trace TTL), fed only by `glea-service` off the durable RabbitMQ queue (no event loss; nack-on-ClickHouse-down). **Tamper-evidence shipped**: a per-`correlation_id` **hash-chain** (`prev_hash`/`seal`) maintained by a background sealer, with `GET /audit/instances/{cid}/seal` to verify the chain. Per-instance audit query (`GET /audit/instances/{cid}`) and a platform-wide window (`GET /audit/metrics`) exist. _(Still deferred: the full **cross-instance Governance & Audit console** — global search, SoD reports, auditor export — for which `/audit/metrics` is the foundation; and **push alerting**, still intended as a scheduled ClickHouse query → notification-service.)_

### Refreshed scorecard (as-built)

| Pillar | Substrate | Enforcement | Surfaced to users | Verdict |
|---|---|---|---|---|
| **Governance** | Strong (roles, SoD, contract-derived egress) | Strong for HITL/SoD; **egress now enforced in native + nemoclaw** | Roles admin UI; governed decisions audited; no authored policy object yet | **Strong; enforcement gap closed** |
| **Lineage** | Strong (pinned `schema_ref` + `input_map` + span links) | N/A (structural) | **Rendered DAG** in the instance view | **Strong + surfaced** |
| **Explainability** | Strong (`actor_log`, proposed-vs-approved, **agent rationale**) | N/A | **Decision trail + trace waterfall + rationale** in-view | **Strong + surfaced** |
| **Audit** | **First-class `audit_events` SoR** (append-only, TTL, **hash-chained**) | Sole-writer, no-loss consumer | Per-instance audit + seal; cross-instance console still to come | **Solid; console deferred** |

### Telemetry reference (as-built)

**Signals.** Traces (OTLP/HTTP → Collector → `otel_traces`) and a fail-soft logs provider are configured by `amendia_telemetry.configure_telemetry`; endpoint absent ⇒ disabled cleanly, Collector down ⇒ no request impact. **No OTel metric instruments (meters) exist** — metrics are SQL aggregations exposed by `glea-service`. Audit is the RabbitMQ → `glea-service` → `audit_events` path (not the logs signal).

**`amendia.*` semantic conventions** (all structural; domain-neutral review gate — no pack/domain term ever enters a span, log, event, or column):

| Attribute | Meaning |
|---|---|
| `amendia.correlation_id` | Instance correlation key — spine of every trace/audit row |
| `amendia.process_instance_id` | Instance id |
| `amendia.pack_key` / `amendia.pack_version` | Which immutable pack version ran |
| `amendia.element_id` | BPMN element |
| `amendia.actor` / `amendia.actor_kind` | Capability id or user id; `capability` \| `human` \| `timer` |
| `amendia.role` | Role that acted/approved |
| `amendia.artifact_key` / `amendia.schema_ref` | Pinned artifact identity (lineage) |
| `amendia.execution_mode` / `amendia.simulation` | `native` \| `nemoclaw`; sim flag |
| `amendia.exec_meta.otlp_trace_id` | Sandbox (nemoclaw) trace correlation |
| `amendia.decision` / `amendia.decided_by` | HITL outcome + approver |
| `amendia.sod_satisfied` | Four-eyes check result |
| `amendia.egress.decision` / `amendia.egress.host` | Egress allow/deny + target |
| `amendia.rationale` | Bounded agent reasoning (deep-agent/LLM only; ~1.2 KB cap) |

**Derived metrics catalog** (SQL over `audit_events` + `otel_traces`; per-instance `GET /audit/instances/{cid}/metrics`, platform-wide `GET /audit/metrics`):

| Figure | Field | Derived from | Pillar |
|---|---|---|---|
| Approval latency p50/p95 | `approval_latency_ms{p50,p95,count}` | `HitlTaskDecided.decided_at − HitlTaskCreated` | governance/SLA |
| Capability exec duration p50/p95 | `capability_duration_ms{p50,p95,count}` | capability span `Duration` in `otel_traces` | ops |
| HITL decisions by decision + role | `hitl_decisions[{decision,role,count}]` | decided audit rows | governance |
| Four-eyes enforced | `four_eyes_enforced` | `sod_satisfied` rows | governance |
| Egress denied | `egress_denied` | `egress_decision='deny'` rows | governance |
| SLA breaches | `sla_breaches` | expiry / SLA-timer rows | SLA |
| Instances by outcome (platform-wide only) | `instances_by_outcome{completed,failed}` | lifecycle rows | audit/ops |

### Original "recommended next moves" — status

1. First-class audit store → **Done** (`audit_events` SoR). 2. Lineage & explanation projection API → **Done** (`/lineage`, `/decision-trail`). 3. Close native-mode egress gap → **Done** (`NATIVE_EGRESS_ENFORCE`). 4. Capture agent rationale → **Done** (`amendia.rationale`, native-mode too). 5. Audit query + export + retention + tamper-evidence → **Partial**: per-instance query + TTL + hash-chain sealing **done**; cross-instance query/export (the console) **deferred**.
