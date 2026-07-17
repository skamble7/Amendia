# Amendia Platform Contracts — Reference & Field Dictionary

**Audience:** platform engineers, capability authors, process-onboarding teams, and maintainers.
**Companion documents:** `amendia_platform_contracts_v1.md` (normative JSON Schemas), `amendia_build_plan.md` (delivery sequence).
**Status:** matches contracts v1 as implemented in `backend/services/agent-runtime/app/models/`.

---

## 1. Why these models exist — the execution story

Amendia executes bank-defined exception-handling processes with AI agents and humans in the loop. Six models carry an exception from arrival to resolution. It helps to read them as a story:

A bank *onboards* a **ProcessPack** — a versioned bundle saying "here is a BPMN process, here is which **Capability** executes each step, here are the **Artifact Schemas** describing every piece of data the steps produce, and here is the *triage rule* saying which exceptions this process handles." Onboarding validates that the whole bundle is internally consistent and that every referenced capability and schema already exists — capabilities are built and registered *before* processes that use them.

At runtime, an exception arrives (via the ingestor). Triage evaluates the active packs' rules and resolves one pack version. The ingestor emits a **Dispatch event**; the agent runtime answers accepted or rejected and creates a **Process Instance** — the living execution record. As the instance runs, capabilities produce artifacts (each validated against its registered schema), gateways branch on artifact fields, and wherever the process demands human judgment, the runtime creates a **HITL Task**. A human decision resumes the instance. Every transition is checkpointed; the pack pin on the instance makes the entire run reproducible and auditable.

So: **ProcessPack** = what to do; **Capability** = who/what can do a step; **Artifact Schema** = the shape of what steps produce; **Dispatch event** = the handoff into execution; **HITL Task** = the human control point; **Process Instance** = the execution itself.

---

## 2. Shared conventions

### 2.1 Identifiers

| Kind | Pattern | Example |
|---|---|---|
| Process pack key | kebab-case | `wire-repair-standard` |
| Capability id | `cap.<domain>.<name>` | `cap.payment.sanctions_screen` |
| Artifact schema key | `art.<domain>.<name>` | `art.payment.repair_verdict` |
| Role id | `role.<domain>.<name>` | `role.payments.ops_approver` |

Domains group by business area (`payment`, `compliance`, …); the platform does not interpret them beyond namespacing, but consistent domains keep registries navigable.

### 2.2 Versioning and `VersionedRef`

Everything versionable uses **semver** (`MAJOR.MINOR.PATCH`). A *reference* is the compact string `<id>@<spec>`:

- In **declaring** positions (a pack's `requires_capabilities`, a binding's `schema`), `spec` may be a range: `^1.0.0`, `>=1.0 <2.0`, or an exact pin.
- In **resolved/runtime** positions (pack `resolved`, dispatch `pack_version`, HITL payload `schema`), `spec` MUST be an exact pin.

**Why ranges then pins:** ranges let pack authors declare tolerance ("any compatible 1.x of this capability"); pinning at pack *activation* freezes exact versions so every run of that pack version is byte-for-byte reproducible — a hard audit requirement in payments. The implementation type `VersionedRef` parses/serializes this form and knows whether it is pinned.

### 2.3 Timestamps, events, routing

All timestamps are UTC ISO-8601. Every event shares three base fields — `event_id` (uuid4, unique per event, used for dedup and causation), `occurred_at`, `schema_version` (self-describing payload version, e.g. `pin.platform.exception_dispatched/1.0`). Routing keys are always built by `amendia_common.events.rk()` as `<service>.<event>.v1` on the `amendia.events` topic exchange. The `<service>`-first hierarchy lets consumers bind per-event-type (`ingestor.exception_dispatched.v1`) or per-service (`agent_runtime.#`).

### 2.4 HITL modes — the platform's safety vocabulary

| Mode | Business meaning | When the human acts |
|---|---|---|
| `none` | Fully autonomous step | Never |
| `review_after` | Agent output is a *draft* until a human confirms it; human may correct it | After execution, before the output enters process state |
| `approve_result` | Agent output stands or falls as-is; no edits | After execution, before downstream steps activate |
| `approve_actions` | Agent may only *propose* real-world actions; human authorizes execution | Before any side effect happens |
| `manual` | The step IS human work; agents may pre-draft | The human performs the task |

Strictness ordering (for policy checks): `none < review_after ≤ approve_result < approve_actions ≈ manual`. Two rules use this ordering: a capability's `min_hitl_mode` is a floor that bindings may tighten but never loosen, and platform policy requires `side_effectful` capabilities to run at `approve_actions` or stricter. Together these make "the AI cannot move money without a human" a *validated property of onboarded configuration*, not a convention.

---

## 3. ProcessPack manifest — "what to do"

**Purpose in execution.** The pack is the unit of onboarding, versioning, and audit. It binds an untouched BPMN 2.0 diagram (the bank's documented procedure) to executable reality: which capability or human role performs each task, under what human oversight, reading and writing which typed artifacts, and which exceptions it applies to. At runtime the pack is the blueprint the agent runtime compiles into an executable graph. Because the BPMN stays byte-stable (hash-verified) and all execution metadata lives in the manifest, the bank's process documentation and the running system can never silently diverge.

### Top-level fields

| Field | Type | Req | Meaning & rationale |
|---|---|---|---|
| `manifest_version` | const `"1.0"` | ✓ | Version of the *manifest format itself*, so the platform can evolve the format while still reading old packs. |
| `pack_key` | string, kebab-case | ✓ | Stable identity of the process across versions. Renaming = a new process. |
| `version` | semver | ✓ | Version of this pack revision. Immutable once stored: changing content requires a new version. |
| `title` / `description` | string | ✓ / – | Human-readable naming for registries, UIs, audit reports. |
| `process` | object | ✓ | Pointer to the BPMN (below). |
| `triage_rules` | array ≥1 | ✓ | When this pack applies (below). |
| `requires_capabilities` | array | ✓ | Declared capability dependencies (below). |
| `artifacts` | array of `art.*@range` | ✓ | Every artifact schema the bindings read or write, declared up front so onboarding can validate the full data surface and the UI can show "this process produces these objects." |
| `bindings` | array ≥1 | ✓ | The heart of the pack (below). |
| `gateway_variables` | array | – | Declares data used by gateway conditions (below). |
| `policies` | object | – | Pack-level governance policies, currently separation-of-duties (below). |
| `status` | `draft` \| `validated` \| `active` \| `deprecated` | ✓ | Lifecycle. Only `active` packs participate in triage; `deprecated` packs finish their running instances but accept no new ones. |
| `created_by` / `created_at` | string / datetime | – | Provenance. |

### `process` — the BPMN pointer

| Field | Meaning & rationale |
|---|---|
| `bpmn_file` | Path/object key of the BPMN 2.0 XML stored alongside the manifest. The XML carries **no** vendor extensions or execution annotations — it remains exactly what the bank documented. |
| `process_id` | The `bpmn:process/@id` inside the file; one file may theoretically hold several processes, this disambiguates. |
| `bpmn_sha256` | Hash of the XML bytes. Computed by the platform at ingest, verified on every load. Guarantees the diagram the bank approved is the diagram that executes. |

### `triage_rules[]` — "which exceptions are mine"

| Field | Meaning & rationale |
|---|---|
| `rule_id` | Stable identifier; recorded in the dispatch event so every routing decision is explainable ("instance X exists because rule Y matched"). |
| `priority` | Integer; lower wins when multiple active packs match one exception. Gives deterministic resolution across a growing catalog. |
| `description` | Human explanation of the rule for onboarding review. |
| `when` | A **predicate tree** evaluated against the normalized exception envelope. |

**Predicate tree.** Combinators `all` (AND), `any` (OR), `not`, over leaves `{field, op, value}`. `field` is a dot-path into the envelope (`payment.msg_type`); `op` ∈ `eq, ne, in, starts_with, intersects, exists, gt, gte, lt, lte` (`intersects` = non-empty intersection between an array field and `value`, the natural operator for reason-code lists). A declarative JSON tree — rather than a scripting language — keeps rules safe to store, render in UIs, and evaluate identically in the registry and anywhere else.

### `requires_capabilities[]`

| Field | Meaning & rationale |
|---|---|
| `ref` | `cap.<...>@<range>` — the declared dependency. Must resolve against the capability registry for the pack to validate; this is the mechanism enforcing "capabilities exist before processes onboard." |
| `resolved` | `cap.<...>@<exact>` — filled by the registry at activation. Absent in drafts. The pin that makes runs reproducible. |

### `bindings[]` — task-by-task execution metadata

One binding per BPMN `serviceTask`/`userTask`; onboarding validates the mapping is a bijection (no unbound tasks, no orphan bindings).

| Field | Meaning & rationale |
|---|---|
| `element_id` | The BPMN flow-node id this binding configures. The join key between diagram and manifest. |
| `element_kind` | `serviceTask` (machine-executed) or `userTask` (human-executed). Must agree with the BPMN element's actual type. |
| `executor` | Discriminated union, `type` = `capability` or `human` (below). |
| `hitl` | `{mode, role}` — oversight applied to this step. `role` (who reviews/approves/performs) is required for every mode except `none`. Note the separation: `executor` says who *does* the step, `hitl` says who *oversees* it — an agent may execute while a different role approves. |
| `inputs[]` / `outputs[]` | Typed data interface of the step (artifactIO, below). Onboarding checks these against the capability's own declared IO and checks that every input is produced upstream (or is seed state) — catching "step 5 reads a dossier nobody produced" at onboarding instead of 2 a.m. |

**`executor` variants.**

| Variant | Fields | Meaning |
|---|---|---|
| `capability` | `capability: cap.*@range` | An agent capability executes the step. |
| `human` | `role: role.*`, `assist_capability?: cap.*@range` | A human in `role` performs the step; `assist_capability` optionally pre-drafts content for them (e.g. an LLM drafts the RFI message the analyst sends). Assist output is always a draft — mode `manual` implies the human owns the result. |

**`artifactIO`** (used in binding and capability IO): `name` — the key this artifact occupies in process state (gateway expressions and downstream inputs address it by this name, e.g. `beneficiary`); `schema` — the `art.*@version` it must conform to; `required` — whether execution may proceed without it (default true).

### `gateway_variables[]`

BPMN gateway conditions (FEEL expressions like `beneficiary.repair_verdict = "repairable"`) read process state. This block declares those reads: `gateway_id` (which gateway), `variable` (the dot-path read, `<stateName>.<field>`), `source_artifact` (which schema defines that field). **Rationale:** conditions live inside BPMN XML where validators can't easily see them; declaring the reads lets onboarding verify each variable is produced by an upstream output *and* that the field is `required` in its schema — so a gateway can never branch on missing data.

### `policies.separation_of_duties[]`

`{constraint: "distinct_actor", elements: [element_ids...]}` — the same human must not act on all listed elements *within one process instance*. This is the four-eyes principle (drafter ≠ approver) expressed as configuration. At runtime, task creation resolves this into concrete `excluded_users` on the HITL task (§7).

---

## 4. Capability descriptor — "who/what can do a step"

**Purpose in execution.** A capability is a versioned, independently registered unit of agent competence — a skill (in-process code/subgraph), an MCP server's tools, or a pure LLM step. Registration *before* pack onboarding is the platform's supply-chain discipline: a pack cannot reference competence that doesn't exist. The descriptor is also the platform's safety database: side-effect classification and HITL floors live here, on the thing that acts, not only on the processes that use it.

| Field | Type | Req | Meaning & rationale |
|---|---|---|---|
| `descriptor_version` | const `"1.0"` | ✓ | Format version of the descriptor itself. |
| `capability_id` | `cap.<domain>.<name>` | ✓ | Stable identity across versions. |
| `version` | semver | ✓ | Immutable revision. New behavior/IO = new version; packs migrate on their own schedule via ranges. |
| `title` / `description` | string | ✓ / – | Registry/UI naming; description should state what the capability actually does — it appears in onboarding reviews. |
| `kind` | `skill` \| `mcp` \| `llm` \| `deep_agent` | ✓ | Execution technology. `skill` = code deployed with the runtime (LangGraph subgraph/function); `mcp` = tools exposed by an external MCP server; `llm` = prompt-defined step with no bespoke code; `deep_agent` = a bounded LangChain Deep Agents loop inside one node (ADR-021), runnable only in `nemoclaw` mode, always behind a HITL gate, always memoized, caged by a `tools` whitelist + the pinned output schema. The kind determines the `runtime` block shape and how the executor invokes it. |
| `side_effect` | `read_only` \| `side_effectful` | ✓ | **The most consequential field.** `side_effectful` = changes state outside Amendia (releases a payment, sends a pacs.004, emails a party). Platform policy: side-effectful capabilities must be bound at `approve_actions` or stricter. Investigation/analysis is `read_only` and may run autonomously. |
| `idempotent` | boolean | – | Whether blind retry is safe. Governs runtime retry behavior: idempotent steps retry freely; non-idempotent ones require an idempotency key or park for human attention on ambiguous failure. |
| `inputs[]` / `outputs[]` | artifactIO | ✓ | The capability's typed contract. Binding IO must be compatible with these — validated at onboarding. Typed IO is what makes capabilities composable across processes and banks. |
| `config_schema` | JSON Schema | – | Declares per-deployment configuration the capability needs (endpoints, list providers, model params). Values live in config-forge; the schema here lets onboarding verify the deployment has supplied valid config before activating a pack. |
| `runtime` | discriminated union | ✓ | How to invoke (below). |
| `constraints.timeout_seconds` | int (default 120) | – | Max execution time before the runtime fails/retries the step. |
| `constraints.max_retries` | int (default 2) | – | Automatic retry budget (subject to `idempotent`). |
| `constraints.min_hitl_mode` | HITL mode | – | Floor demanded by the capability author regardless of pack bindings. Example: sanctions screening insists its result is at least human-approved. Bindings may be stricter, never looser. |
| `owner` | string | – | Team/party accountable for the capability. |
| `status` | `active` \| `deprecated` | ✓ | Deprecated capabilities fail new pack validation but keep serving already-active pinned packs. |
| `created_at` | datetime | – | Provenance. |

**`runtime` variants.**

| Kind | Fields | Notes |
|---|---|---|
| `skill` | `entrypoint` | Python path (`amendia_caps.payment.enrich:run`) resolved inside the runtime process. |
| `mcp` | `endpoint`, `tools[]`, `transport`, `headers` | **Self-descriptive (ADR-024):** `endpoint` is the MCP server URL, declared directly on the capability (no config-forge/registry indirection — the descriptor carries what it needs; the trade-off is the endpoint is environment-specific). `tools` whitelists exactly which MCP tools this capability may call — the agent gets those and nothing else; `transport` ∈ `streamable_http` (default), `stdio`, `sse`; `headers` are non-secret headers or secret-refs (`env:`/`file:`/`vault:`) — never a literal secret. |
| `llm` | `prompt_key`, `model_config_key`, `structured_output` | Prompt and model config indirect into config-forge so prompts are versioned/managed, not buried in code; `structured_output` (default true) = output is parsed and validated against the declared output artifact schema. |
| `deep_agent` | `prompt_key`, `model_config_key`, `tools[]`, `structured_output`, `budget{max_steps,max_tokens}` | ADR-021. A bounded Deep Agents loop; `tools` is the whitelisted toolset (worker functions and/or MCP tool ids) — the **only** tools the loop may call; `model_config_key` resolves to a managed/`nemoclaw` ref; `budget` caps the loop (max_steps → LangGraph recursion_limit). Registry-gated: HITL-required, `read_only`-unless-justified, tools must resolve, nemoclaw-only. |

---

## 5. Artifact schema registration — "the shape of what steps produce"

**Purpose in execution.** Artifacts are the typed objects flowing through a process instance: dossiers, verdicts, draft instructions, screening results. Registering their shapes as JSON Schemas is what makes the platform's data flow *checkable*: onboarding proves producers and consumers agree; the runtime rejects malformed writes at the producing step (where the bug is) instead of a confusing failure three steps later; HITL screens render artifacts from their schemas; gateways branch on fields guaranteed to exist.

### Registration envelope

| Field | Type | Req | Meaning & rationale |
|---|---|---|---|
| `artifact_key` | `art.<domain>.<name>` | ✓ | Stable identity across versions. |
| `version` | semver | ✓ | Immutable revision, semantics below. |
| `title` / `description` | string | ✓ / – | Registry/UI naming. |
| `json_schema` | object | ✓ | A complete JSON Schema draft 2020-12 document describing instances of this artifact. |
| `compatibility` | `backward` (default) \| `none` | – | Whether the registry enforces compatibility on minor/patch submissions. `backward` = a diff check rejects breaking changes disguised as minors. `none` opts out (rare; discouraged). |
| `tags` | string[] | – | Free-form discovery aid. |
| `status` | `active` \| `deprecated` | ✓ | As with capabilities. |
| `created_at` | datetime | – | Provenance. |

### Conventions (enforced at registration)

1. `json_schema` must be draft 2020-12, root `"type": "object"`, its own `$id` set to `https://amendia.dev/schemas/artifacts/<domain>/<name>/<version>.json`, and should set `additionalProperties: false` (warned otherwise) — closed shapes keep agent outputs honest.
2. **Semver semantics:** patch = docs/examples only; minor = backward-compatible additions (new *optional* fields, widened enums); major = anything breaking (remove/rename fields, new required fields, narrowed types).
3. `$ref` only to other *registered* schema `$id`s — no external URLs; the registry is a closed, auditable universe.
4. The runtime validates every artifact **write** against the pinned version at execution time; failure fails the task — never silent coercion.
5. Fields used as gateway variables must be `required` (checked during pack validation, see §3).

> **Form-driven onboarding (ADR-025).** The process-registry's `OnboardingSession` state machine can
> **infer** these registrations from a running MCP server: introspect a compliant tool, and its
> `inputSchema`/`outputSchema` are normalized to rules 1 & 3 above (draft 2020-12, forced root object,
> canonical `$id`, `additionalProperties: false`, external-`$ref` rejection) to produce an input artifact,
> an output artifact, and one `kind: mcp` capability — with nothing written to the catalog until commit.

---

## 6. Dispatch event — "the handoff into execution"

**Purpose in execution.** The moment an exception stops being a record and starts being work. Emitted by the ingestor after triage; consumed by the agent runtime; the accepted/rejected reply closes the loop and drives the ingestor's `dispatched → accepted/rejected` lifecycle. Deliberately **thin** — identity plus routing decision plus a fetch URL, never the payload — so messages stay small, never stale, and access to exception detail stays behind the fetch-back API.

Routing keys: `ingestor.exception_dispatched.v1`; replies `agent_runtime.dispatch_accepted.v1` / `...dispatch_rejected.v1`.

### `exception_dispatched`

| Field | Req | Meaning & rationale |
|---|---|---|
| `event_id` | ✓ | Unique event identity (uuid4); dedup + causation anchor. |
| `occurred_at` | ✓ | When dispatch happened. |
| `schema_version` | ✓ | `pin.platform.exception_dispatched/1.0` — self-describing payload. |
| `exception_id` | ✓ | The exception being dispatched. |
| `exception_type` | ✓ | Cheap filter/telemetry without a fetch. |
| `exception_schema_version` | – | Envelope schema of the underlying exception (e.g. `pin.payments.wire_exception/1.0`) so the runtime knows how to parse what it fetches. |
| `fetch_url` | ✓ | Where the runtime pulls the full envelope (the source store's fetch-back API). Keeps the event thin and the source authoritative. |
| `resolution.pack_key` | ✓ | Which process was chosen. |
| `resolution.pack_version` | ✓ | **Exact pinned version.** The instance runs this and only this revision, whatever gets activated later. |
| `resolution.rule_id` | ✓ | Which triage rule matched — every routing decision is explainable in audit. |
| `resolution.resolved_at` | – | When triage decided. |
| `trace.correlation_id` | ✓ | Stable id across the whole exception journey (defaults to `exception_id`); lets logs/metrics/events from stub → ingestor → runtime → UI be stitched into one thread. |
| `trace.causation_id` | – | `event_id` of the `exception_raised` event that led here — the parent link in the event chain. |

### Replies

`dispatch_accepted`: base fields + `process_instance_id` (the instance created or — on redelivery — already existing), `pack_key`, `pack_version`; `trace.causation_id` = the dispatch `event_id`.

`dispatch_rejected`: base fields + `reason` ∈ `unknown_pack` (no such pack), `pack_not_active` (resolved version not active), `fetch_failed` (couldn't retrieve envelope), `envelope_invalid` (retrieved but fails validation), `capacity` (backpressure), plus free-text `detail`. The enum is deliberately closed: the ingestor and dashboards can react programmatically per reason.

**Idempotency.** The runtime treats `(exception_id, pack_key, pack_version)` as the instance idempotency key. Redelivered or duplicate dispatches return the existing `process_instance_id` in a fresh `dispatch_accepted` — broker redelivery can never double-execute an exception.

---

## 7. HITL task / approval model — "the human control point"

**Purpose in execution.** The single work-item shape behind every human touchpoint, whatever the mode: reviewing an agent's verdict, approving a repair as-is, authorizing a side-effectful action, or performing a manual step with an agent-drafted starting point. One shape means one inbox, one decision API, one audit trail. Mechanically: a graph node interrupts → a task document is created → the UI surfaces it → a decision arrives → the graph resumes with that decision. The decided task + surrounding checkpoints form the four-eyes audit record.

### Identity & context

| Field | Req | Meaning & rationale |
|---|---|---|
| `task_id` | ✓ | Unique work-item identity. |
| `process_instance_id` | ✓ | The instance awaiting this human. |
| `pack_key` / `pack_version` | ✓ | Which process (pinned) generated the task — the UI renders against exactly this revision's expectations. |
| `element_id` | ✓ | Which BPMN node the task belongs to — the diagram highlight in the UI and the join back to the binding. |
| `exception_id` | ✓ | Business anchor; inboxes group and search by it. |
| `hitl_mode` | ✓ | One of the four non-`none` modes — determines UI treatment and default decisions. |
| `role` | ✓ | Role whose members may claim the task (from the binding's `hitl.role`). |
| `title` / `description` | ✓ / – | What the human sees in the inbox. |
| `priority` | – | `low` \| `normal` (default) \| `high` \| `critical` — inbox ordering; wire exceptions with cutoff pressure run high. |
| `due_at` | – | SLA deadline; past it the task may transition to `expired` and escalate per runtime policy. |

### Assignment & separation of duties

| Field | Meaning & rationale |
|---|---|
| `assignee` | User id once claimed; null while open. Claiming prevents two operators duplicating work. |
| `sod.excluded_users` | Users who must NOT decide this task — computed at task creation from the pack's `distinct_actor` policies by looking up who actually acted on the conflicting elements *in this instance*. Four-eyes enforced per-instance with concrete names, not abstract policy. Checked at claim AND at decide (membership may change between). |
| `sod.derived_from` | The element_ids whose actors were excluded — so the UI can explain *why* someone can't claim ("you drafted this repair"). |

### Payload — what the human reviews

| Field | Meaning & rationale |
|---|---|
| `payload.artifacts[]` | Typed snapshots under review: `name` (state key), `schema` (**pinned** `art.*@x.y.z` — the UI renders the form/view from this schema version), `data` (the instance). Snapshots, so the task shows exactly what existed at interrupt time. |
| `payload.proposed_actions[]` | Only for `approve_actions`: the side effects awaiting authorization. `action_id` (stable id for partial approval), `kind` (machine-readable action type, e.g. `release_payment`, `send_pacs004`), `summary` (one human-readable line — this is what the approver is legally signing off), `detail` (full structured parameters). |
| `payload.context_url` | Deep link into the UI's exception + instance view for full context beyond the snapshot. |

### Decision

| Field | Meaning & rationale |
|---|---|
| `allowed_decisions` | The legal verdicts for this task, derived from mode: `review_after` → approve / edit_and_approve / reject; `approve_result` → approve / reject; `approve_actions` → approve / reject (optionally partial); `manual` → complete / escalate. Closed set → the UI renders exactly the right buttons and the API rejects anything else. |
| `status` | `open → claimed → decided`, plus `cancelled` (instance terminated while waiting) and `expired` (past `due_at`). Immutable after `decided` — audit demands the record never changes. |
| `decision.decision` | The verdict; must be in `allowed_decisions`. |
| `decision.decided_by` / `decided_at` | Who and when — the accountability core. |
| `decision.comment` | Free-text rationale; effectively mandatory for `reject` in ops practice. |
| `decision.edits` | For `edit_and_approve`: the *full replacement* artifact data, re-validated against the pinned schema before the graph resumes — a human cannot accidentally break the data contract either. |
| `decision.approved_action_ids` | For partial `approve_actions`: which proposed actions were authorized; absent = all. Unapproved actions are not executed. |
| `created_at` / `updated_at` | Store timestamps. |

**Decision → runtime mapping:** `approve`/`complete` resume forward; `edit_and_approve` replaces the artifact then resumes; `reject` on review/result modes re-runs the producing capability once then escalates (v1 policy); `reject` on `approve_actions` = actions NOT executed, graph takes the pack-defined rejection path; `return_for_rework` resumes backward to the producing node; `escalate` re-creates the task for a supervisor role.

**Task events** (thin, for the notification service → UI): `agent_runtime.hitl_task_created.v1` and `...hitl_task_decided.v1` carrying `task_id`, `exception_id`, `process_instance_id`, `element_id`, `role` (+ `decision`, `decided_by` on decided).

---

## 8. Process instance — "the execution itself"

**Purpose in execution.** The runtime-owned aggregate representing one exception being handled by one pinned pack version. Referenced by dispatch replies and HITL tasks; the anchor for checkpoints, audit queries, and the UI's instance view. (Runtime-internal — not part of the five onboarding contracts, documented here because everything else points at it.)

| Field | Meaning & rationale |
|---|---|
| `process_instance_id` | Unique instance identity (`PI-…`). |
| `exception_id` | Which exception this instance handles. |
| `pack_key` / `pack_version` | The **pinned** process revision executing. Never changes for the life of the instance, even if newer pack versions activate — in-flight work is never silently migrated. |
| `status` | `created` (accepted, not yet running) → `running` → `waiting_hitl` (interrupted on a human) → `completed` \| `failed` \| `cancelled`. The coarse-grained state for dashboards; fine-grained position lives in checkpoints. |
| `correlation_id` | Propagated from the dispatch trace; joins the instance into the end-to-end journey. |
| `idempotency_key` | Derived from `(exception_id, pack_key, pack_version)`, unique-indexed — the mechanical guarantee behind dispatch idempotency (§6). |
| `created_at` / `updated_at` | Store timestamps. |

---

## 9. How the models interlock

| Relationship | Enforced |
|---|---|
| Pack binding → capability (exists, in range, active, kind-consistent IO) | Registry, at pack validation |
| Pack binding hitl ≥ capability `min_hitl_mode`; side_effectful ⇒ ≥ `approve_actions` | Registry, at pack validation |
| Binding & capability IO → artifact schema (exists, compatible version) | Registry, at pack validation |
| Gateway variable → upstream output artifact, field `required` | Registry, at pack validation |
| Pack activation → ranges pinned (`resolved`) | Registry, at activation |
| Exception → pack (triage rule, priority) | Ingestor via registry `resolve`, at dispatch |
| Dispatch → instance (pinned version, idempotency key) | Runtime, at dispatch handling |
| Instance → HITL task (element binding, SoD exclusions from instance actors) | Runtime, at interrupt |
| Task decision → allowed_decisions, SoD, schema-validated edits | Runtime, at decide |
| Artifact write → pinned schema validation | Runtime, at every step output |

Read top-to-bottom, this table is the platform's safety argument: by the time an agent executes anything, every reference has been resolved, every data shape agreed, every human gate placed, and every version pinned.

---

## 10. Glossary

**Pack / ProcessPack** — versioned onboarding bundle: BPMN + bindings + rules + dependencies. **Binding** — per-BPMN-task execution metadata. **Capability** — registered, versioned unit of agent competence (skill/MCP/LLM). **Artifact** — typed data object in process state; **artifact schema** — its registered JSON Schema. **Triage** — matching an exception to a pack via predicate rules. **Dispatch** — the ingestor→runtime handoff event pair. **Pin** — an exact version resolved from a range at activation. **HITL** — human-in-the-loop; **HITL task** — the work item representing one human touchpoint. **SoD** — separation of duties (four-eyes). **Instance** — one execution of one pack version for one exception. **Correlation id** — journey-wide trace id. **Idempotency key** — the tuple preventing duplicate instances.
