# Amendia as Data Processor — Gap Analysis against the Flagstar ⇄ Mphasis PII Exchange Security Architecture (v1.7)

**Status:** assessment, pre-decision. Input to **ADR-065**.
**Assessed:** 2026-08-18, against the working tree at `/Users/sandeep/Documents/Projects/Amendia` (uncommitted state as of the 2026-08-13 fresh redeploy).
**Reference document:** *PII: Design for sensitive data*, v1.7 (Aug 13, 2026) — Flagstar as **data controller**, Mphasis as **data processor**.
**Companion diagram:** *PII: Design for sensitive data — Version 3 (Aug 4, 2026)*.

---

## 1. Scope and boundary

The reference architecture draws the processor side ("Payment Operations Platform") as five boxes: **Gateway**, **Decrypt service**, **Data Store**, **Orchestrator**, **Agent**. That diagram predates Amendia and does not map cleanly onto it. For this analysis the boundary is fixed as follows, per the project owner:

| Diagram box | Amendia? | Note |
|---|---|---|
| **Agent** | **Yes** | The agent-runtime executes the process. |
| **Orchestrator** | **Yes** | Same component — Amendia *is* the orchestrator; there is no separate one. |
| **Data Store** | **Yes** | Amendia owns MongoDB **and** ClickHouse. PII landing there is Amendia's responsibility. |
| **Decrypt service** | **Open** | Not built. Whether Amendia implements it or calls a sibling POP service is **Decision D1** (§7). |
| **Gateway** | **Open** | Not built as a distinct Amendia component. |
| MCP-server datastores | **No** | Outside the Amendia boundary. Amendia is *not* accountable for how an MCP server stores what it receives — but **is** accountable for what it sends (§5.F). |

One consequence is worth stating up front, because it reframes the whole document. §4.6 of the reference architecture assigns the end-of-day purge explicitly to the processor's orchestrator:

> *"The case orchestrator at the processor end is actively aware of all active cases and their retention period. Hence, the orchestrator can initiate a data purge at the processor end, and log its completion."*

That orchestrator is Amendia. The retention obligation is not adjacent to Amendia; it lands inside `agent-runtime`.

## 2. Method

Findings were derived by direct inspection of the working tree over the device bridge, not from documentation or inference. Every claim below carries a `file:line` citation and is marked **Confirmed** (read in the source) or **Inferred**. Five parallel audits covered ingress/persistence, HITL/authoring surfaces, observability, egress, and retention/authorization; the highest-severity findings were then independently re-verified against the source before being recorded here.

Where the reference document itself is ambiguous or looks unimplementable as written, that is flagged in §8 rather than silently resolved.

## 3. Executive summary

**Amendia is built on an assumption the reference architecture invalidates: that the trigger payload is ordinary business data.** Every store, every log, every event and every outbound call is designed around that assumption. The platform is domain-neutral by deliberate design (ADR-047/049/059) — it does not know what a wire, an account number or an SSN is, and nothing in it distinguishes a sensitive field from a case identifier.

That is not a defect of execution. It is a scope boundary that was never crossed, and it has been crossed now by the decision to place Amendia on the processor side of a PCI/GLBA-scoped exchange.

Against the reference architecture's processor-side obligations, the position is:

| Obligation area | Status | Worst finding |
|---|---|---|
| Field-level encryption at rest | **Absent** | Plaintext JSON in ≥7 Mongo collections |
| Key management / unwrap callback | **Absent** | No key-vault client, no DEK, no wrapped key |
| Dispatch-derived grants / purpose limitation | **Absent** | Standing RBAC; any role-holder may act on any case |
| Retention / de-hydration / crypto-shred | **Absent** | No TTL, no purge, no per-case delete API |
| No PII in observability | **Violated** | Confirmed leak path into 7-year ClickHouse retention |
| Controlled egress | **Violated** | Full case envelope sent to AWS Bedrock, unredacted |
| Masked-by-default human access | **Inverted** | UI detects IBAN/account fields to render them *more* legibly |
| Tamper-evident access log | **Scaffolded, inert** | Hash-chain columns exist, explicitly never written |

**Counts:** 9 Critical, 11 High, 6 Medium, 2 Low — 28 findings.

**Nothing in the current codebase field-encrypts, masks, tokenizes, redacts or classifies customer data. This was verified by exhaustive search, not assumed.** The one genuine data-minimization control that exists — the notification-service SSE allow-list — is correct, well-built, and covers a single channel out of many.

Two findings are severe enough to warrant action ahead of any ADR:

1. **G-19 (Critical):** every `llm`-kind capability serialises the **entire trigger envelope and all upstream artifacts** into a prompt and sends it to AWS Bedrock (`us-east-1`, third-party inference) with no redaction — and this path is *explicitly excluded* from the platform's own egress blocking.
2. **G-14 (Critical):** a JSON-schema validation failure embeds the offending **value** into an error string that is logged twice, persisted to Mongo, published on the bus, and written verbatim into a ClickHouse column with ~7-year retention.

Both are live in the running stack today, on synthetic data. Neither requires an attacker.

---

## 4. Where sensitive data would come to rest today

Mapped against the reference architecture's Appendix A list of "the places data leaks from". Amendia hits nearly every item on it.

| # | Store | Owner | What lands there | Written at | Encrypted? | Expiry? |
|---|---|---|---|---|---|---|
| 1 | `trigger_messages.payload` | stub-trigger-generator | Full raw envelope, verbatim | `stub_trigger_generator/app/dal/trigger_repo.py:28` | No | None |
| 2 | ingestion record `.trigger_detail` | ingestor | **Second full copy** of the envelope | `backend/services/ingestor/app/dal/ingestion_repo.py:44` | No | None |
| 3 | `lg_checkpoints` / `lg_checkpoint_writes` | agent-runtime | `ProcessState.envelope` + all `artifacts`, re-serialised **at every graph-node boundary** | `app/engine/engine.py:136`, state at `app/engine/state.py:39-41` | No | None |
| 4 | `capability_memo.outputs` | agent-runtime | Full capability output values, per instance/element/attempt | `app/engine/executor/memo.py:87` | No | None |
| 5 | `hitl_tasks.payload` | agent-runtime | `PayloadArtifact.data` + `ProposedAction.detail` (the exact tool argument object) | `app/dal/hitl_task_repo.py:23`, built `app/engine/task_runner.py:814` | No | None |
| 6 | `sample_triggers` | agent-runtime | Fixture envelopes seeded from `worked-examples/` | `app/seeding/load.py:120` | No | None |
| 7 | `onboarding_sessions.trigger_fields` | process-registry | Derived from deployment sample envelopes | `app/models/onboarding.py:393` | No | None |
| 8 | ClickHouse `audit_events.payload` | glea-service | **Entire raw event JSON**, verbatim | `app/events/mapper.py:86` | No | ~7 yr TTL |
| 9 | RabbitMQ durable queues | all | Event bodies incl. free-text `rationale` / `comment` | various | No | **No TTL, no DLQ** |
| 10 | Mongo `process_instances.last_error` | agent-runtime | Failure detail incl. schema-validation messages | `app/engine/engine.py:771` | No | None |

Item 3 deserves emphasis. `app/engine/state.py:4-6` states the design intent plainly:

> *"Everything here is JSON-serializable so the Mongo checkpointer can persist it at every node boundary — that checkpoint trail is the audit record."*

The checkpoint trail is simultaneously the resumability mechanism, the audit record, and — under the new scope — the largest and most frequently rewritten PII store in the platform. §7/D3 returns to this.

---

## 5. Gap register

Severity: **C**ritical (blocks go-live / active exposure), **H**igh, **M**edium, **L**ow.

### A. Data protection at rest

**G-01 · C · No field-level encryption exists anywhere.**
*Obligation:* §3.5, §4.2 — authenticated field/column-level AES-256-GCM (JWE `A256GCM`) for SSN and account number, sitting **on top of** volume encryption, keyed from the controller-rooted hierarchy.
*Current:* Confirmed by exhaustive search across `backend/`, `libs/`, `stub_trigger_generator/`, `mcp_stub/`, `pega_stub/`, `webui/` for `encrypt|decrypt|kms|hsm|dek|mask|redact|tokeniz|pii|sensitive|classif`. The only hits are LLM credential resolution (`libs/polyllm/src/polyllm/secrets.py`) and *process* classification (`cohort_classifier.py`). Every store persists via `model_dump(mode="json")` → `insert_one`. Disk-level encryption, if any, is infrastructure and is explicitly not sufficient per §3.5.

**G-02 · C · The envelope is replicated across at least four independent stores with no inventory.**
Items 1–5 in §4. The reference architecture's crypto-shred guarantee requires that *every* copy be keyed from the same wrapping-key hierarchy (Appendix A, Data Store: *"each must be keyed from the same wrapping-key hierarchy… otherwise crypto-shredding the case would leave recoverable residue"*). Today there is no hierarchy and no registry of copies.

**G-03 · C · No key hierarchy, therefore crypto-shred is impossible by construction.**
No wrapped-DEK is stored alongside any ciphertext because there is no ciphertext. Deletion would have to be a data-hunting exercise across items 1–10, which is precisely the failure mode §3.5 and Appendix A are designed to avoid.

**G-04 · M · No data classification layer at the envelope boundary.**
Nothing marks a field as SSN / account / PAN / non-sensitive. Domain neutrality means the platform cannot infer it. Any field-level control (encryption, masking, minimization, log scrubbing) needs this layer first — it is the common prerequisite for G-01, G-07, G-13..G-18 and G-24.

### B. Key management and the unwrap callback

**G-05 · C · No decrypt service, no key-vault client, no unwrap callback.**
*Obligation:* §3.3 and Appendix A — the processor holds ciphertext plus a wrapped DEK and must call back to the controller's HSM per read, presenting a grant and a per-request ephemeral public key; the DEK returns HPKE-wrapped (RFC 9180, P-256/HKDF-SHA-256/AES-256-GCM).
*Current:* No component, client, config or contract for any of this exists. This is the single largest net-new build on the processor side.

**G-06 · H · No DEK cache, therefore no TTL discipline to tune.**
§3.4 / flow (c) step 7 assume a memory-only, short-TTL, per-key cache with aggressive clearing — and §6 lists the TTL as an open decision whose value trades revocation sharpness against latency. Amendia has no cache and no place to put one. Note §4.8: the latency budget and the TTL must be set together, and both are `[TBA]`.

### C. Grants and purpose limitation

**G-07 · C · Authorization is standing, role-based and global. There is no case-scoped, field-scoped or expiring grant.**
*Obligation:* §3.7 — authority derives from the controller's dispatch record, issued as a grant bound to one case and one field set, expiring with the unit of work.
*Current:* `libs/amendia_auth/dependencies.py:93` `require_roles` is a static endpoint guard. HITL claim/decide checks only `task.role in actor_roles` (`app/services/hitl_service.py:56`) — **any holder of the role may claim and decide any open task of that role, on any case**. The repo says so itself: `backend/docs/operations/FAQ/Roles_FAQ.md:92` — *"No permissions / scopes / entitlements / policy engine exist."* The only per-instance narrowing is SoD, and SoD is a *negative* exclusion (who may not act), not a positive grant.

**G-08 · H · No purpose-to-field mapping, and no minimization at ingress.**
*Obligation:* §4.5 — the controller maintains a per-work-type field allow-list; the dispatch emits only permitted fields, in the permitted form.
*Current:* Amendia receives and stores the entire envelope regardless of what the process needs. The pack's `input_map` (ADR-048) is the closest analogue but is a design-time data-flow binding used to shape a tool call, not an enforced minimization boundary — and it operates *after* the full envelope has already landed in three stores.

**G-09 · H · Service-to-service authentication is a single static shared secret.**
*Obligation:* §4.1 — mutual TLS on both endpoints, certificate-bound access tokens (RFC 8705), leaf certs ≤90 days auto-rotated, CA/SPKI pinning with overlap procedure, FAPI 2.0 alignment.
*Current:* `X-Amendia-Internal`, compared with a plain `==` (not constant-time) at `libs/amendia_auth/dependencies.py:111`, with the **same literal value across every service** (`backend/deploy/docker-compose.yml:121,154,246,280,339,428`). Never expires, never rotates, no per-caller identity. The library carries its own TODO at `settings.py:35`: *"replace the shared static token with mTLS / signed service tokens."*

**G-10 · M · No anti-replay controls.**
§4.1 requires `jti` / `iat` / `exp` / `aud` on every signed payload and unwrap request, a replay cache at each receiving gateway covering the acceptance window, idempotency keys on push, and 0-RTT disabled. Amendia has idempotency at the *capability* level (memoization, ADR-019) but no message-level anti-replay anywhere.

### D. Retention, deletion, de-hydration

**G-11 · C · No automatic expiry of case data exists anywhere.**
The **only** Mongo TTL index in the entire codebase is `pending_messages` at 1 hour (`app/db/mongo.py:77`) — an ADR-031 correlation buffer, unrelated to case data. ClickHouse TTLs cover observability only. Zero hits repo-wide for `crypto-shred`, `shred`, `dehydrat`, `rehydrat`.

**G-12 · C · The end-of-business-day retention policy has no implementation, and it is not an edge case.**
*Obligation:* §4.6 — *"any case that is not resolved on any given business day will be drained from its case detail data."*
This collides directly with how Amendia works. A process instance parks in `WAITING_HITL` waiting for a human approver; cases routinely span days by design. Under §4.6, **de-hydration is the normal path for any case that crosses a business-day boundary awaiting approval**, not a rare cleanup. Every such instance must be drained nightly and re-hydrated on resume.

**G-13 · C · The LangGraph checkpoint trail is both the resumability mechanism and the PII store.**
This is the sharpest architectural collision in the analysis. `ProcessState.envelope` and `ProcessState.artifacts` are serialised into `lg_checkpoints` at every node boundary (`app/engine/state.py:4-6,39-41`). De-hydration must purge exactly the data that makes an instance resumable, and the same trail is described in-code as the audit record. Encrypting channel values, excluding sensitive fields from graph state entirely, or purging-and-re-hydrating checkpoints are three genuinely different architectures with different blast radii. See Decision **D3**.

**G-14 · H · No per-case or per-instance deletion API exists at all.**
Repo-wide `@router.delete` sweep: identity, process-registry (packs / onboarding / cohort definitions / membership), config-forge. **Nothing in agent-runtime.** No purge-on-completion, despite flow (e) steps 4–7 assigning exactly that to the orchestrator ("*orchestrator instructs the decrypt service to purge the case details… logs the fact*").

**G-15 · H · No re-hydration path.**
Flow (g) is a processor-*initiated* pull against the controller, presenting a grant, receiving a freshly-keyed payload. Amendia's ingress is push-plus-fetch-back at case start only; it has no concept of asking the controller for case data mid-flight.

**G-16 · M · Known orphan: `capability_memo` survives pack deletion (CB-2).**
`backend/docs/known-issues/cleanup-backlog.md:27-45` accepts this as won't-fix for a dev tool — *"orphaned-but-inert"*. Under the new scope, "inert" is wrong: an orphaned memo holds full capability outputs derived from case data, and nothing reaches it. CB-2 should be reopened at a different severity.

**G-17 · H · `hitl_tasks`, `capability_memo`, `sample_triggers` and `onboarding_sessions` are retained indefinitely with full payload data.**
None carries a TTL index. Under §4.6's defined retention with secure deletion, all four are unbounded PII stores.

### E. Observability as a leak surface

The reference architecture is categorical here (Appendix A, Data Store): *"No SSN, account number, or PAN — not even a token where the schema expects an identifier — may enter these pipelines… treat any sensitive value found in observability data as an incident."*

**G-18 · H · `audit_events.payload` stores the entire raw event JSON verbatim, for ~7 years.**
`glea-service/app/events/mapper.py:86` — `"payload": orjson.dumps(payload).decode("utf-8")`, into the `payload String` column at `app/clickhouse/schema.py:199`, under `TTL toDateTime(occurred_at) + INTERVAL {ttl_days} DAY` with `ttl_days` ≈ 7 years (`config.py:34`). Whatever any event ever carries lands here in full and stays.

**G-19 · C · Confirmed end-to-end leak: schema-validation failures embed the offending value and propagate to five sinks.**
`jsonschema`'s `ValidationError.message` includes the instance value by design (e.g. `"'123-45-6789' does not match pattern"`). `app/engine/task_runner.py:588-593` builds that message into `verr`. It then reaches:
1. `task_runner.py:635` — `logger.warning(...)`
2. `task_runner.py:648` — wrapped into `NodeExecutionError`
3. `engine.py:421` — `logger.exception(...)` with full traceback
4. `engine.py:771,773` — persisted to Mongo `last_error`, logged again
5. `engine.py:787-792` — published as `ProcessFailedEvent.detail` → consumed by glea → **`audit_events.payload`, 7-year retention**

No scrubbing at any hop. Confirmed by full code trace.

**G-20 · H · HITL resume and decision payloads are `repr()`'d into exception text.**
`task_runner.py:731` (`f"invalid resume payload: {resume!r}"`), `:772,859,909` (`{decision!r}`), `:794` (validation error against the reviewer's **edited** artifact). Same propagation path as G-19 — so a human approver's edits to a case artifact can end up in ClickHouse.

**G-21 · H · The `amendia.rationale` span attribute is unscrubbed model output, by documented design.**
`task_runner.py:387` sets it; `libs/amendia_telemetry/tracing.py:177-191` only length-bounds it to 1200 chars and states in its own docstring: *"the value is model content (not scrubbed)."* Since the model's input is the full envelope (G-22), the rationale can echo case data into traces.

**G-22 · H · `ArtifactCommittedEvent.rationale` carries the same unscrubbed model output onto the bus and into ClickHouse.**
`libs/amendia_contracts/governance_events.py:111-114`.

**G-23 · H · No redaction or scrubbing exists anywhere in the pipeline.**
`backend/deploy/otel/collector-config.yaml` and `deploy/helm/amendia/templates/otel-collector.yaml` both run `processors: [batch]` only — no `attributes`, `redaction`, `filter` or `transform` processor. All six services' `logging_conf.py` are plain `StreamHandler` + a `ContextFilter` that stamps `request_id`/`trigger_id`. No PII-scrubbing `logging.Filter` exists in the codebase.

**G-24 · H · The tamper-evidence scaffold is present but inert.**
`app/clickhouse/schema.py:201-203` declares `prev_hash` and `seal` with the comment *"RESERVED for the deferred hash-chain fast-follow — present in the schema, NEVER written in Phase B."* Appendix A requires the access log and evidence ledger to be append-only with cryptographic chaining, stored away from the systems they record. The columns exist; the chain does not.

**Credit where due — G-25 · (no gap) · The notification-service SSE allow-list is correct.**
`notification-service/app/events/signal_mapper.py:45-79` — a genuine allow-list of ten id/enum fields, with no bypass path (verified: `app/main.py:38-40` publishes only `to_signal()` output), and a backend test asserting that `due_at`/`detected_at`/`ref`/`clock`/`correlation_value` are **absent**. This is the pattern the rest of the platform needs, and it already exists in-house.

### F. Egress

**G-26 · C · Every `llm`-kind capability sends the full unredacted envelope and all upstream artifacts to AWS Bedrock.**
`app/engine/executor/dispatch.py:135-139`:
```python
{"role": "user", "content": (
    f"Trigger:\n{json.dumps(envelope, default=str)}\n\n"
    f"Upstream artifacts (inputs):\n{json.dumps(inputs, default=str)}"
)}
```
The configured provider is real, not simulated: `docker-compose.yml:313` sets `AGENTRT_SIMULATION_MODE: "false"`; `:315` sets `AGENTRT_LLM_CONFIG_REF: dev.llm.bedrock.explicit-creds`, resolving via `config-forge-service/scripts/seed.py:176-197` to Bedrock `anthropic.claude-3-5-sonnet-20241022-v2:0` in `us-east-1`. This is unconditional for any `llm` node.

**G-27 · C · The `llm` and `deep_agent` paths are explicitly exempt from egress blocking.**
`task_runner.py:236-238`, in the source: *"`mcp` hosts are enforceable; `llm`/`deep_agent` default to **audit-only** — their concrete provider host is resolved from ConfigForge and can legitimately differ from the proxy host, so blocking them risks breaking a real call."* The deny is recorded and the call proceeds. So the platform's own egress control cannot stop the highest-volume PII egress path it has.

*Regulatory note, for legal rather than architectural determination:* §5.1 classifies AWS as a sub-processor **in its hosting role** — compute, storage, queues, connectivity — and argues the exposure is bounded because AWS handles "only ciphertext and tokens, never cleartext SSN, account number, or PAN." A Bedrock inference call is a different service consuming **cleartext** and is not covered by that reasoning. Whether the existing AWS DPA flow-down reaches it is a contract question that should be put to Flagstar explicitly rather than assumed.

**G-28 · H · MCP capabilities without an authored `input_map` send the entire envelope to the MCP server.**
`app/engine/executor/core.py:290-292`: `arguments = mcp_args if mcp_args is not None else {"envelope": ctx.envelope, "inputs": inputs}`. MCP-server *storage* is out of Amendia's boundary — but *what Amendia transmits* is squarely Amendia's minimization obligation under §4.5.

**G-29 · H · The egress allow-list is self-referential, not curated.**
`app/engine/executor/policy.py:92-114` derives the allow-list from the capability descriptor's **own declared endpoint** — it verifies "we dialled the host we said we would", not "this host is approved". Any pack author can point `McpRuntime.endpoint` at an arbitrary host and it is auto-allowed. §5 requires a default-deny chokepoint (NAT/egress gateway or forward proxy), FQDN allow-listing, a controlled DNS resolver, and flow-log anomaly detection. None exists; `docker-compose.yml` puts all services on one default bridge with no network policy.

**G-30 · M · No TLS enforcement on MCP endpoints.**
`McpRuntime.endpoint` is a bare `str` (`libs/amendia_contracts/capability.py:68-77`); nothing rejects `http://`. §4.1 requires TLS-only listeners with no plaintext path and no redirect-based upgrade.

**G-31 · H · No dead-letter queue, no queue TTL, no message field encryption.**
Repo-wide: zero hits for `x-dead-letter-exchange`, `x-message-ttl`, or any `arguments=` on a queue declaration; every `declare_queue()` passes only `durable=True`. Stock `rabbitmq:3-management` with no policy config. Appendix A treats queues and DLQs as first-class PII stores requiring field encryption, bounded retention, and coverage by the crypto-shred hierarchy. Amendia has unbounded durable queues holding plaintext JSON.

**G-32 · L · MCP header secret-refs are documented but never resolved.**
`capability.py:76` requires secret **references** (`env:`/`file:`/`vault:`) and forbids literals, but no resolution code was found in agent-runtime. Either refs go out unresolved (functional bug, low risk) or a literal placed there is transmitted verbatim (no guardrail enforces the rule).

### G. Human access to cleartext

**G-33 · H · There is no masking anywhere — and the UI actively optimises sensitive fields for readability.**
`webui/src/components/artifact/ArtifactView.tsx:32-39`:
```ts
const isId = /id$|uetr|iban|bic|account/i.test(keyName);
```
…which selects monospace/tabular rendering **so account numbers and IBANs are easier to read accurately**. That is a sensible UX decision for non-sensitive data and the exact inverse of §4.4's requirement for masked-by-default tooling with unmasking gated by an explicit, logged, separately-authorized action. No reveal gate, no truncation, no redaction exists in `webui/src`.

**G-34 · H · No field-read access log.**
Appendix A (Audit & DLP) requires a record of *"every read of an SSN or account-number field — the identity of the caller, the timestamp, the specific record or field accessed."* Amendia logs decisions and transitions (`actor_log`, which is clean — `app/engine/state.py:92-101` carries only ids/timestamps, correctly), but an approver opening a task and reading its contents leaves no access record at all. Without this there is no processor-side stream to reconcile against the controller's unwrap log.

**G-35 · M · No endpoint control.**
§4.7 requires cleartext to be rendered only in a VDI / zero-download session with no local storage, and a visible watermark identifying agent, session and timestamp. Amendia's webui is an ordinary SPA. (Browser-side persistence is otherwise clean — only OIDC tokens in `sessionStorage` at `webui/src/auth/oidc.ts:30`, plus a session-scoped BPMN diagram cache.)

**G-36 · M · No DLP.**
No content inspection for sensitive-value egress exists on any path.

### H. Non-production data hygiene

**G-37 · M · Worked-example fixtures carry PII-shaped values and are seeded into the live database.**
`backend/docs/methodology/worked-examples/wire_transfer/schemas/wire_exception.sample.json` contains a well-formed IBAN (`DE44500105175407324931`), BICs, and realistic counterparty names; `stub_trigger_generator/app/generator.py:44-58` hardcodes the same shapes. These are loaded into the runtime `sample_triggers` collection by `app/seeding/load.py:120`. The values appear synthetic — but §4.5 bans PII from non-production environments, and PII-*shaped* fixtures in a production-adjacent store defeat the DLP and classification controls that would later be built on top of them.

### I. Reconciliation and evidence

**G-38 · H · No unwrap-correlated access log, and no joint log schema.**
Appendix A requires the processor's access log and the controller's unwrap log to share correlation identifiers and identical field semantics, versioned as a **joint interface control document**, with the processor's feed shipped off-processor in near-real time before it can be altered locally. GLEA is the closest thing Amendia has and is genuinely well-positioned (see §6), but today it carries no grant id, no unwrap correlation, no policy version, no decision/reason code in the required sense, and it is not tamper-evident (G-24).

---

## 6. What Amendia already has that helps

This is not a rebuild from zero. Several existing pieces are directly load-bearing for the target design, and it is worth being explicit about them before scoping ADR-065.

- **Domain neutrality (ADR-047/049/059) is an asset here, not an obstacle.** Because the platform handles an opaque `payload` and no service reasons about field meaning, a classification-and-protection layer can be inserted at the envelope boundary without touching process logic, the BPMN compiler, or any pack.
- **The durable timer substrate (ADR-029, extended by ADR-064) is the right foundation for end-of-day de-hydration.** It already provides idempotent registration (`$setOnInsert` on a unique key), a crash-durable `fire_at` poller, and guarded compare-and-set transitions giving exactly-once fire across restarts — `app/dal/timer_repo.py`, `app/dal/cohort_sla_repo.py`. A de-hydration sweep is a new timer *kind* plus a purge handler, not a new substrate.
- **GLEA is the evidence-ledger scaffold.** Append-only ClickHouse, long retention, and `prev_hash`/`seal` columns already declared for the deferred hash chain. Completing that chain and adding grant/unwrap correlation turns it into the processor-side feed Appendix A asks for.
- **`signal_mapper` is the in-house pattern for allow-listed data minimization**, with a test asserting the absence of non-whitelisted fields. Generalise it; don't invent a second approach.
- **ADR-060 pack ownership + ADR-048 `input_map` + declared artifact schemas** are the raw material for a purpose-to-field mapping: the platform already knows, per pack version, which fields each capability consumes.
- **SoD, four-eyes, `allowed_decisions` and HITL floors already exceed what the reference architecture asks on approval control** — §4.4 asks for least privilege and dual authorization; Amendia computes SoD per instance from who actually acted.
- **ADR-061's audit-first delete cascade** (emit the audit event *before* removing rows, so the record survives the deletion) is exactly the pattern crypto-shred logging needs.
- **`EgressDecisionEvent` already exists as a concept** — the hook for a real egress policy is in place; only enforcement and a curated allow-list are missing.
- **The cohort `correlation_value`** is already the cross-system case handle, and maps cleanly onto the controller's case identity for grant scoping and reconciliation.

---

## 7. Decisions this forces

These are for the project owner and Flagstar jointly; ADR-065 should not silently pick any of them.

**D1 · Does Amendia implement the decrypt service, or call a sibling POP component?**
The diagram shows them separate; the reality is that Amendia owns the stores the decrypted data would flow into. Implementing it inside agent-runtime is simpler and keeps the DEK cache next to its consumer; splitting it out creates a smaller, more auditable component holding the grants and the key-vault client, at the cost of a network hop per unwrap.

**D2 · Does Amendia ever hold cleartext at rest, or only in memory?**
The reference architecture assumes the processor stores ciphertext and decrypts in memory at point of use. Amendia's current design stores everything, repeatedly. Committing to ciphertext-at-rest is the cleanest posture and the one that earns the encryption safe harbour (§2) — but it forces D3.

**D3 · How is the LangGraph checkpoint reconciled with encryption and de-hydration?** *(the hard one)*
Three materially different options:
- *(a)* **Encrypt channel values** — keep the state shape, wrap sensitive values in the checkpointer serde. Least disruptive; means every node boundary triggers key operations, and the checkpoint still holds ciphertext that must be crypto-shredded.
- *(b)* **Keep sensitive fields out of graph state entirely** — the state carries references; the decrypt service resolves them at point of use inside a node. Cleanest PII posture, largest change to the execution model, and it breaks the "checkpoint trail is the audit record" property that ADR-011 relies on.
- *(c)* **Purge checkpoints at EOD and rebuild on re-hydration** — matches §4.6 literally; requires that an instance be reconstructible from a re-hydrated envelope plus its `actor_log`, which is not true today.

**D4 · Who mints the grant, and what does Amendia's dispatch record look like?**
§3.7 requires the *controller* to mint grants from *its* dispatch record. Amendia has `dispatch_log` and a resolution record, which is the processor-side mirror. The joint contract — grant format, scope vocabulary, expiry semantics, and how a HITL wait that spans days interacts with grant lifetime — has to be agreed with Flagstar, not designed unilaterally. Note the interaction: a case parked in `WAITING_HITL` for two days outlives any short grant.

**D5 · Is any external LLM inference acceptable on cleartext PII?**
If no: `llm`-kind and `deep_agent` capabilities must be barred from sensitive fields, or moved to in-VPC inference. If yes: it needs explicit sub-processor flow-down (see G-27's regulatory note) and, at minimum, field-level minimization of the prompt. This decision gates whether the agentic parts of Amendia can touch protected fields at all — which is close to gating the product thesis for this engagement, and should be settled early.

**D6 · Does the processor actually need cleartext for as many fields as the document assumes?**
The reference architecture asserts the processor needs cleartext SSN and account number "to do its job", and tokenizes only PAN. That premise is worth re-testing against Amendia's real ACH-exposure and wire-repair processes: where a capability *matches, compares or routes on* a value rather than *reading* it, a token or a deterministic hash may serve — which would move those fields into the PAN treatment and shrink the cleartext surface substantially. This is a scope-reduction opportunity to raise with Flagstar, not merely a compliance obligation to absorb.

---

## 8. Notes on the reference document itself

Raised here as review points, not gaps:

1. **§4.6's end-of-day retention is stated as a general rule but reads as though authored for short-lived processing.** For a human-in-the-loop orchestrator it makes de-hydration the normal path for any case awaiting approval overnight. Either the policy needs an explicit carve-out for cases parked on a human gate, or the re-hydration flow (g) needs to be understood as high-frequency rather than exceptional. Worth confirming which was intended.
2. **§3.7 grants and long-lived cases are in tension.** A grant "expires with the unit of work", but a unit of work here can be a multi-day approval. Grant refresh semantics for a parked case are unspecified.
3. **§4.8's placeholders are load-bearing.** The unwrapped-key TTL and the latency budget must be set together (the document says so), and the availability/RTO of the key vault caps the whole exchange — but a fail-closed key vault also means Amendia cannot execute at all during a vault outage. The operational consequence for in-flight instances deserves a line in §4.8.
4. **Editorial:** v1.7 still carries visible tracked-change residue in several places (e.g. §3.3, §4.1–4.2, Appendix A "Controller-operated keysBYOK", "BYOK / HSMCONTROLLER-OPERATED HSM", Appendix D's PAN entry "the 134- to 19-digit"). Appendix C's PII/PCI columns carry unresolved `?` markers and a stray footnote numbering. Worth a clean pass before it goes to a QSA or an examiner.
5. **The document does not name an agentic processor.** It assumes deterministic processing. It has no position on whether an LLM may see cleartext, what an agent's tool-call arguments constitute for minimization purposes, or how model output (rationales, drafted artifacts) should be classified. Given that Amendia is the processor, this is a genuine hole in the reference architecture — and Amendia's own findings G-21, G-22, G-26 all sit in it.

---

## 9. Suggested sequencing

Not a plan — an argument about order, for the ADR conversation.

**Ahead of any ADR** (small, contained, reduce live exposure now):
- G-19/G-20 — stop validation-error and `repr()` values reaching logs, `last_error`, the bus and ClickHouse.
- G-26/G-27 — decide D5; until decided, gate `llm`-kind capabilities off protected packs.
- G-23 — a scrubbing processor in the collector and a logging filter, even a crude one, is strictly better than none.

**ADR-065 · Data classification and the protected-envelope boundary** — G-04 first, because G-01, G-08, G-13..G-24 and G-33 all depend on the platform being able to tell a sensitive field from an identifier.

**Then, roughly in dependency order:** the decrypt-service/key-vault client and envelope encryption (D1–D3, G-01/G-05) → grants and minimization (D4, G-07/G-08) → retention, de-hydration and crypto-shred on the timer substrate (G-11..G-15) → the reconciliation feed and evidence chain (G-24/G-34/G-38) → egress chokepoint and mTLS (G-09/G-29/G-31) → masked-by-default UI and endpoint control (G-33/G-35).

The observability and egress fixes are cheap and immediate; the encryption, grant and retention work is one coherent architecture and should be decided together rather than phased apart.
