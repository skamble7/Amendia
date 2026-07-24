# Amendia — Process Onboarding Guide

**The canonical, detailed reference for onboarding a process (ProcessPack) into Amendia.** It captures every
step, field, validation, finding code, and gotcha as the platform stands today, and is a **living document** —
updated as capabilities land (currently reflects the platform **through ADR-043: full BPMN *ingestion* +
*Common Executable* execution, plus real business-error mapping (ADR-035), multi-instance activities
(ADR-036), native DMN decision tables (ADR-037), the collection-reduction / summary capability (ADR-038),
cross-pack composition via callActivity (ADR-039), cooperative cancellation — an interrupting timer
boundary on a running serviceTask (ADR-040), scope-level cancellation — interrupting timer/error
boundaries on a subProcess (ADR-041), the event sub-process — a scope-wide interrupting error/timer
handler, at process level or nested (ADR-042), compensation — explicit compensate-throw + reverse-order
undo of committed side effects (ADR-043), the onboarding **element-coverage catch-up** — the wizard now
authors the full bindable set the runtime executes, single fidelity (ADR-044), **swimlane / persona
inference UX** — lane personas drive pre-filled HITL + role descriptions and candidates carry their provenance
(ADR-045), and **decision / reduce authoring** — a business user authors a native-DMN decision table or a reduce
config in the wizard, no code (ADR-046) — completing the wizard catch-up: the wizard now authors everything the
runtime executes** — plus **operator-testing UX refinements** (batch 1): the BPMN step collapses its input to a
summary after parse and focuses the coverage report, capability **reuse is now an on-demand search dialog**
(`GET /capabilities?q=`) instead of an eager catalog list, the Bindings step **pre-selects each capability
task** from the inference (a "suggested" chip + the HITL floor applied) so bindings arrive pre-filled, and an
**unselected capability is a clean field-level `bindings_invalid` error** (never a raw 500 at assemble),
**domain-neutrality remediation P0** — the capability **domain has no business default** (operator-chosen, else
derived from the pack_key), a **`capability_id_collision`** guardrail flags a staged id already active in the
catalog, and **seeding is opt-in** (no hardcoded seed path; the platform boots clean with `SEED_DIR` unset), and
capability **`input_map`** (ADR-048) — each input's data is sourced from the trigger or an upstream output, so
an MCP-per-process pack chains and executes (and fails validation, not at runtime, when it can't); finding
codes, profiles, and endpoints **reconciled against the source on 2026-07-18**).

- **Audience:** Process Owners (who operate the onboarding wizard) and platform engineers (who need the
  contract/validation detail underneath).
- **Companion docs:** `amendia_platform_contracts_v1.md` (normative JSON Schemas), `amendia_contracts_reference.md`
  (field dictionary), `amendia_services_reference.md` (endpoints), `amendia_mcp_implementor_guideline.md`
  (MCP server rules), `amendia_bpmn_deferred_backlog.md` (what isn't executable yet), ADRs 010/024/025/026 and
  027–034 (BPMN conformance program).
- **Scope note:** this guide is about *authoring/onboarding* a pack. Runtime execution is covered by
  `amendia_agent_runtime_execution_pipeline.md`.

---

## Table of contents

1. What a process onboarding actually is
2. The mental model (read before your first onboarding)
3. Prerequisites
4. The onboarding flow — the `OnboardingSession` state machine, step by step
5. The 7-stage validator (what "validated" proves)
6. Execution profiles & what actually runs (ingest Full / execute Common Executable)
7. The two entry points (wizard vs seeder)
8. What happens after activation
9. Roles a pack references
10. Capabilities & artifacts — the dependencies you onboard first
11. Finding-code catalog (errors vs warnings)
12. BPMN element support matrix
13. Troubleshooting & common gotchas
14. Worked example (wire-repair-agentic)
15. Glossary

---

## 1. What a process onboarding actually is

A **ProcessPack** is the versioned unit a bank onboards. It bundles:

- a **BPMN 2.0 diagram** — the bank's documented procedure, byte-stable and hash-pinned. Amendia treats it as
  the *blueprint*; it carries **no execution annotations**.
- a **manifest** — all execution metadata: which capability or human role runs each task, under what
  human-in-the-loop (HITL) oversight, reading/writing which typed artifacts, plus triage rules and policies.
- **declared dependencies** — the **capabilities** (units of agent competence) and **artifact schemas** (typed
  JSON shapes) the tasks use, which must exist *before* the pack can validate.

Onboarding is the act of turning that documented BPMN into an **executable, validated, version-pinned, active**
pack. Nothing runs until a pack is `active`; once active it is immutable (frozen and reproducible).

**Two fidelities of one diagram (ADR-027):** Amendia *ingests* the **full** BPMN notation (for documentation
and to infer pack components) but *executes* the **Common Executable** subset. A diagram may be richer than
what runs; the onboarding wizard tells you exactly which parts execute (see §6). This is the "classify, don't
reject" principle: a valid-but-not-executable element is a **warning/annotation**, never a hard rejection.

---

## 2. The mental model (read before your first onboarding)

Five ideas explain almost everything you'll see:

1. **Dependencies exist first.** Artifact schemas and capabilities are registered *before* a manifest that
   references them can validate. The canonical order is **artifact schemas → capabilities → manifest → BPMN →
   validate → activate**. The wizard stages the new ones and writes them in exactly this order at commit.
2. **The manifest is the source of truth for execution; the BPMN is the source for documentation & inference.**
   The BPMN is hash-pinned and richer than what runs; the *committed manifest* is what the runtime executes.
3. **Classify, don't reject (ingestion).** Full BPMN is accepted; each element is tiered
   `executable | documented | unknown`. Only genuinely malformed BPMN (or a not-yet-executable construct on the
   *live path*) blocks you.
4. **Execution profiles gate what runs.** A pack's minimum required profile (`common_subset` or
   `common_executable`) is **derived from its BPMN** and pinned at activation; a runtime refuses a pack it
   can't run, up front, with `pack_requires_profile`. Default is `common_executable` (ADR-034).
5. **Immutability & pinning.** A `pack_key@version` is frozen once `active`/`deprecated`. Ranges (`^1.0.0`) in
   the manifest are pinned to exact versions at activation for byte-for-byte reproducibility. Changing anything
   means a **new version**.

Two safety properties are *validated configuration*, not conventions: **a side-effectful capability cannot run
without a human authorization gate**, and **the drafter cannot approve their own work** (separation of duties).

---

## 3. Prerequisites

- **Role:** every onboarding mutation requires **`role.process.owner`** (403 otherwise, naming the missing
  role). Reads and `GET /roles` are open to any authenticated principal.
- **A running, compliant MCP server** *if* you will create MCP capabilities: it must be **up and reachable at
  onboarding time**, serve **streamable HTTP**, and be **Amendia-MCP-compliant** (every tool declares
  `inputSchema` *and* `outputSchema`; action tools return an acknowledgement; self-contained schemas — see
  `amendia_mcp_implementor_guideline.md`). Non-compliant tools cannot be selected.
- **Your BPMN's `process_id`** (`bpmn:process/@id`) — the wizard prefers a process marked
  `isExecutable="true"`, else matches by id.
- **Know your deployment's execution profile.** If the deployment runs `common_subset`, a pack using richer
  constructs will onboard but **won't activate/run** there until the deployment enables `common_executable`.
- **Capabilities/artifacts that already exist** can be reused from the catalog; only **MCP** capabilities are
  *created* in this flow (skill/llm/deep_agent are reuse-only).

---

## 4. The onboarding flow — the `OnboardingSession` state machine

Onboarding is a **backend-owned state machine** (ADR-025). The webui wizard is a thin renderer: each step POSTs
to one endpoint, the backend mutates the session and returns the full session, and the UI re-renders. Nothing
is written to the catalog until **commit** — new artifacts/capabilities are *staged* on the session, so an
abandoned onboarding leaves no orphaned immutable rows.

**States (one transition each):**
`initiated → bpmn_attached → capabilities_resolved → bindings_set → triage_set → policies_set → assembled →
completed`.

**The invalidation cascade:** re-editing an upstream step clears dependent downstream state (and the session
reports what was cleared, `last_cleared`). Re-attaching BPMN clears bindings + gateway variables + SoD and
re-derives the inventory + inference; re-staging capabilities clears bindings + gateway variables; any staged
change drops the dry-run. This is why you work top-to-bottom.

Session management: `GET /onboarding` (list your sessions), `GET /onboarding/{id}` (resume — sessions are
resumable), `DELETE /onboarding/{id}` (abandon; safe — nothing was written).

### Step 1 — Basics · `POST /onboarding` → `initiated`

Creates the session.

| Field | Rule |
|---|---|
| `pack_key` | kebab-case, `^[a-z][a-z0-9-]*$` (e.g. `wire-repair-standard`). Stable identity across versions. |
| `version` | semver `MAJOR.MINOR.PATCH`. Immutable once active. |
| `title` | required, human-readable. |
| `description` | optional. |
| `default_domain` | `^[a-z0-9_]+$` — the `cap.<domain>.*` / `art.<domain>.*` id namespace. **Operator-chosen, no business default**; omit it to **derive from the pack_key** (sanitized). Keep it **process-scoped** so ids don't collide with the active catalog (a colliding id is flagged at the Capabilities step — see below). |

**409** if `pack_key@version` already exists as an `active`/`deprecated` pack — bump the version to onboard a
revision.

### Step 2 — BPMN · `PUT /onboarding/{id}/bpmn` → `bpmn_attached`

Upload or paste the BPMN XML (upload also sets `bpmn_file`). On success the backend:

- **Selects the process** (`isExecutable="true"` preferred, else exact `process_id`), parses the **whole
  `<definitions>`**, and **classifies every element**: `executable` (runs), `documented` (valid BPMN outside
  the executable set — lanes, pools, message flows, and any construct above the deployment profile),
  `unknown` (unrecognized). Produces a **coverage report** (counts + per-element tiers).
- **Extracts semantics** for inference (Phase 1.1): lanes (+members), pools/participants, message flows,
  events (+subtype), boundary attachments, gateway conditions, DMN `decisionRef`, data objects, sub-process
  containment.
- **Runs inference** (Phase 1.2) → an **advisory `InferenceDraft`** on the session (see the steps it pre-fills
  below). Nothing is committed; it seeds the forms.

**Hard errors (block, `severity: error`):** unparseable XML (`bpmn_parse_error`), no matching process
(`bpmn_process_not_found`), a `sequenceFlow` into a documented/unknown node (`bpmn_dangling_flow` — this is how
an *on-path* non-executable element is caught), start/end count problems, conditionless exclusive flow. **A
construct above the deployment's execution profile** (e.g. a parallel gateway under `common_subset`) blocks
**activation**, surfaced at assemble/commit — not at attach.

**Warnings (do not block, `severity: warning/info`):** documented elements (`bpmn_documented_element`), unknown
elements (`bpmn_unknown_element`). These are the "classify, don't reject" annotations.

**UI:** once a BPMN parses, the (tall) upload / paste input **collapses to a one-line summary** (`✓ BPMN
attached · <file|pasted> · N executable, M documented`) and the **coverage report scrolls into focus**; a
**Replace / edit** control re-expands the input (invalidation is unchanged). The diagram is one click away via
**View diagram**.

> **The single most common mistake:** uploading the *reference* (full-notation, documentation) BPMN instead of
> the *executable* projection. A diagram with lanes/pools/message-flows *off* the live path onboards fine; but
> a construct *on* the sequence-flow path that isn't executable (or is above the profile) will block. See the
> two-layer model in §6 and the worked example in §14.

### Step 3 — Capabilities · `POST /capabilities/introspect-mcp` then `POST /onboarding/{id}/capabilities` → `capabilities_resolved`

Three things happen here: **reuse** existing catalog capabilities, **create new MCP capabilities**, and
**author inline `decision` / `reduce` capabilities** (ADR-046) — all staged in one `POST
/onboarding/{id}/capabilities` (body `{tools, decision_specs, reduce_specs, reused_capability_refs}`).

**Reuse is on-demand (UI):** the step no longer eager-loads the whole active catalog. **"Reuse a capability"**
opens a **search dialog** that queries `GET /capabilities?q=<term>&status=active&limit=20` (a new **`q`**
free-text substring over `capability_id` + `title`) only once you type; selected reuses show as **removable
chips**. The step's focus is the MCP-introspect section + the inferred candidates + the decision/reduce builders.

**Introspect** (`POST /capabilities/introspect-mcp`, body `{endpoint, transport?, headers?, domain}`): connects
to the MCP server, calls `tools/list`, returns each tool with a **compliance verdict**. Non-compliant tools
(missing `outputSchema`, non-object root, external `$ref`) **cannot be selected**. Owner-gated, `http(s)`-only,
timeout-bounded (SSRF surface).

**Stage** (`POST /onboarding/{id}/capabilities`): for each selected tool, the wizard **infers**:
- an **input artifact** from `inputSchema` and an **output artifact** from `outputSchema` — normalized to
  Amendia conventions (draft 2020-12, root `type: object`, canonical `$id`
  `https://amendia.dev/schemas/artifacts/<domain>/<name>/<version>.json`, `additionalProperties: false`,
  external `$ref` rejected). Suggested keys `art.<domain>.<tool>_input/_output` — editable.
- one **`kind: mcp` capability** — `runtime {kind: mcp, endpoint, tools:[tool], transport, headers}`, wired to
  the two artifacts. Suggested id `cap.<domain>.<tool>` — editable.

**You MUST set two things MCP can't tell us, per tool:**
- **`side_effect`** (`read_only` default | `side_effectful`). This is the most consequential field:
  `side_effectful` forces the binding to `approve_actions` or stricter downstream.
- **`idempotent`** (safe to blind-retry?).

**Id-collision guardrail:** a newly-staged capability id (`cap.<domain>.<tool>`) that **already exists as an
active catalog capability** is refused here (`capability_id_collision`, naming the id + active version) — the
`cap.<domain>` namespace clash is why the domain must be process-scoped. To *reuse* an existing capability, add
it via **"Reuse a capability"** (the search dialog) instead of re-authoring its id; otherwise pick a distinct
domain.

**Author `decision` / `reduce` inline (ADR-046, `decision_specs[]` / `reduce_specs[]`):** the step has two
form-driven builders (no code, no MCP server). A **decision-table builder** (input/output columns + hit policy +
rules-as-a-grid, each input cell a bounded unary test) and a **reduce builder** (source list + `item_path` + op +
predicate + `output_field`). On stage each is **live-validated by the shared `dmn`/`reduce` checks** (surfacing
`dmn_*`/`reduce_*` as field errors) and its output artifact is **inferred** (a decision's verdict — each output
column a required, gateway-branchable field, literal columns → an enum; a reduce's summary — the `output_field`
typed by the op). `side_effect` is always `read_only`; the **input** references an existing/staged upstream
artifact. The Track-3 "decision table candidate" badge on a `businessRuleTask` is a one-click *author* action.

**Creation is MCP-only.** To use a `skill`/`llm`/`deep_agent` capability, **reuse** it from the catalog
(`reused_capability_refs`, `<cap-id>@<range>`), validated to exist + be active now (re-checked at commit).

Inference also pre-fills **capability candidates** (which tasks/message-flows expect a capability) as hints.

### Step 4 — Bindings · `PUT /onboarding/{id}/bindings` → `bindings_set`

One binding per **bindable element** — the **bijection** (exactly one binding per element, no orphans, no
unbound tasks). **Single fidelity (ADR-044):** the reference BPMN *is* the executable one — everything on the
sequence flow is bound and executes; lanes/pools/message-flows are `documented` decoration. The wizard now
authors the **full bindable set** the runtime executes (`bpmn.bindable_elements`): the whole standard task set +
message catch/receive tasks + callActivities + nested sub-process tasks + `isForCompensation` handlers. The
`subProcess` / event-subprocess **containers** are structural and are **never** bound.

Each binding maps an element to an **executor category** by its BPMN kind (`TASK_EXECUTOR_CATEGORY`, ADR-033):

| BPMN element_kind | Executor | Notes |
|---|---|---|
| `serviceTask`, `sendTask`, `scriptTask`, `businessRuleTask` | **capability** | `sendTask` naturally side-effectful; `businessRuleTask` = a bound capability, or a native DMN `decision` capability (ADR-037) |
| `userTask`, `manualTask` | **human** | HITL; `manualTask` defaults to `manual` |
| `receiveTask`, `messageCatch` | **message** | correlated by business anchor; no HITL gate (ADR-031) |
| `callActivity` | **call** | invokes another pack inline — `pack` + `version` range + `input_map`/`output_map`; no HITL of its own (ADR-039) |

Per binding: `element_id`, `element_kind`, `executor` (`{type: capability, capability: cap.*@range}` /
`{type: human, role: role.*, assist_capability?}` / `{type: message, message_name}` /
`{type: call, pack, version, input_map, output_map}`), `hitl {mode, role}` (capability/human only),
`inputs`/`outputs` (artifactIO), and — for a capability — an **`input_map`** (ADR-048).

**Input sourcing (ADR-048):** a capability binding's `input_map` declares **where each input's data comes
from** — `{from: trigger, path?}` (the process trigger, whole or a dotpath), `{from: artifact, name, path?}` (a
named upstream output), or `{fields: {…}}` (a composite object built from a mix). This is what makes an
**MCP-per-process pack chain**: introspected tools emit `<tool>_output` and need `<tool>_input`, so per-tool
inputs never share names — the map wires the entry task from the **trigger** and later tasks from **upstream
outputs**, and (for `mcp`) becomes the tool-call `arguments`. The step **pre-fills** each source **field by
field** (ADR-048 D4): reading the tool schemas, it matches every input field to an **upstream output field**
(`{from: artifact, name, path}`) or a **trigger path** (`{from: trigger, path}`), emitting a composite
`{fields: {…}}`; an **entry** task sources the whole trigger. The suggestion is keyed off the **bound
`capability_ref`**, never a name guess: `set_capabilities` seeds an initial hint from the pre-selected
capability, then `set_bindings` **authoritatively** refills each capability binding's `input_sources` from *its
own* bound capability's schemas + the upstream producers' outputs (filling only inputs the operator left unset)
— so a task whose **BPMN element name diverges from its tool id** still gets a full field-level map once bound.
The trigger is **opaque** today (no declared trigger
artifact — ADR-047 deferred), so a field with no upstream producer defaults to a trigger path (the only
remaining origin, validated as satisfiable); each pre-filled field carries a **"suggested"** chip and the
operator overrides via the composite picker. A binding **without** `input_map` chains by shared artifact name (unchanged). It is
**validated** (below): an input that is neither mapped nor produced upstream is a hard error, not a runtime
death. The binding UI renders an executor sub-form per category and shows
`multi-instance` / `compensates …` / `event-subprocess` badges. Inference pre-fills executor + lane-derived role
with a **provenance chip** ("from lane: Ops Analyst"); a `businessRuleTask` shows a **decision-table-candidate**
badge. **Capability pre-select (UX):** each capability task is **pre-selected** with its inferred capability
(`InferredBinding.suggested_capability_id`) matched against the staged/reused set — **exact id** first, then a
**confident name-token** match, else left "Select…" — shown with a **"suggested"** chip; the pre-select triggers
the same **HITL floor bump** as a manual pick (so a side-effectful task shows `approve_actions` immediately,
never a misleading `none`). A human task's **executor role and HITL role both default to the lane role** (same
value, editable). So bindings arrive pre-filled and the operator changes only disagreements. **Lane persona →
starting HITL (ADR-045):** the task's lane sets the *starting* HITL mode — an
**agent/automation** lane → `none`, an **analyst/maker** lane → `review_after`, an **approver/checker** lane →
`approve_actions`, a **supervisor** lane → `manual` (a lane-less/unrecognized lane falls back to the verb
heuristic). This is only a starting point — the **side-effect→HITL floor below is the hard constraint** (a
side-effectful capability is always ≥ `approve_actions`, even in an agent lane). Everything is editable. **Only
the backlog's deferred stretches are refused** — at the assemble dry-run, via the existing registry codes (e.g.
a non-interrupting or message-triggered event sub-process, transaction/targeted/multi-instance compensation),
never silently bound.

**Policies pre-fills (ADR-045):** SoD pairs come pre-filled from lane-crossing maker/checker candidates, each
carrying its **rationale** as a dismissible "suggested" chip (accept or remove); each pack **role** is seeded
with its lane **persona description** (approver / analyst / agent …), operator-editable, carried into the
`pack_roles` sidecar. The Capabilities step turns each **external message flow** into an actionable
capability-slot nudge (the provider name + suggested id + "introspect for this").

**Guards enforced here (field-level errors):**
- **Required executor ref:** a `capability` executor must name a capability (`field: capability_ref`), a `human`
  a `role`, a `message` a `message_name`, a `call` a `call_pack`. An **unselected capability** — a task left
  "Select…", or a `businessRuleTask` whose decision was never authored — is a **hard 422 `bindings_invalid`
  naming the element**, surfaced inline on that row. It is *not* a server error: the same guard also runs in
  `_compose` (so a stale, pre-existing binding fails `assemble`/`commit` with the clean 422, never a raw 500 at
  manifest validation).
- **Kind agreement:** `element_kind` matches the BPMN element; serviceTask→capability, userTask→human, etc.
  (`binding_kind_mismatch` / `executor_kind_mismatch`).
- **HITL role required** for every mode except `none` (`hitl_role_missing`).
- **Side-effect → HITL coupling:** a `side_effectful` capability requires HITL mode ≥ `approve_actions`
  (`side_effect_requires_approve_actions`); every binding must be ≥ the capability's `min_hitl_mode`
  (`hitl_below_capability_floor`). The response carries `allowed_min_mode` so the UI greys out weaker modes.
- **Bijection:** `duplicate_binding`, `unbound_task`, `orphan_binding`.

**HITL modes** (strictness `none < review_after ≤ approve_result < approve_actions ≈ manual`): `none`
(autonomous), `review_after` (approve / edit-and-approve / reject the produced artifact), `approve_result`
(approve/reject as-is), `approve_actions` (approve side-effects before they execute — the money-moving gate),
`manual` (a human performs it; an `assist_capability` may pre-draft).

### Step 5 — Triage · `PUT /onboarding/{id}/triage` → `triage_set`

At least one rule. Each: `rule_id`, `priority` (integer; **lower wins** across matching active packs),
`description?`, `when` (a **predicate tree**). Predicate: combinators `all`/`any`/`not` over leaves
`{field, op, value}`, `op ∈ eq, ne, in, starts_with, intersects, exists, gt, gte, lt, lte`. `field` is a
dot-path into the normalized exception envelope. Validated syntactically and smoke-tested against sample
envelopes (`triage_rule_invalid` / `triage_rule_smoke`).

> **Triage is not inferable from the BPMN** — it matches the exception *envelope*, not the diagram. You author
> it. **Watch priority collisions:** if two active packs match the same envelope, lowest priority wins — scope
> a test pack to a distinct reason code or a winning priority to avoid hijacking another pack.

### Step 6 — Policies · `PUT /onboarding/{id}/policies` → `policies_set`

- **`gateway_variables`** — each exclusive gateway's FEEL variable (`<stateName>.<field>`) declared with its
  `source_artifact`. Validation (stage 6) requires the field be **`required`** in an **upstream-produced**
  artifact schema, else `gateway_variable_not_required` / `gateway_variable_unproduced` /
  `gateway_variable_schema_missing`. Pre-filled from inference (you supply `source_artifact`).
- **`separation_of_duties`** — `distinct_actor` over **≥2** element ids (`sod_too_few_elements`,
  `sod_unknown_element`). Four-eyes: the drafter can't approve. Inference proposes cross-lane draft/approve
  candidates.
- **`roles`** — pack-local, derived from the bindings' `hitl.role` / human `executor.role` plus any declared.
- **`role_meta`** (optional) — `{role_id → {label, description}}`, filtered to roles in the derived set. At
  commit it's written to the `pack_roles` sidecar and surfaced by `GET /roles` to the admin Assign-role picker
  (ADR-026). Metadata only; the runtime never reads it.

### Step 7 — Assemble · `POST /onboarding/{id}/assemble` → `assembled`

Composes the full `ProcessPackManifest` from staged data and **dry-runs the real 7-stage validator** against
the staged (not-yet-registered) artifacts/capabilities via read-only overlays — so you see all 7 stages
(including gateway-variable-resolves-to-a-required-field) **before** anything is written. Returns the
`dry_run_report` (grouped by stage; the UI offers per-error "Fix" jumps). A clean dry-run is **advisory** — the
catalog can change before commit, so commit re-validates.

### Step 8 — Commit · `POST /onboarding/{id}/commit` → `completed`

Runs the ordered, idempotent chain (identical to the seeder), recording `commit_progress` per step:

1. **Register artifact schemas** (`409 already-exists ⇒ done`).
2. **Register capabilities** (staged mcp caps written; reused refs re-checked active).
3. **Submit pack manifest** as `draft`.
4. **Attach BPMN** (store XML + sha256, keep `draft`).
5. **Validate** with the real repos — if not clean, stop, persist the report, leave the session at `assembled`
   (`validation_failed`); **never activate on a stale green dry-run**.
6. **Activate** — pin every capability/artifact range to an exact version, write the **resolution sidecar**
   (pins + `required_execution_profile` derived from the BPMN, ADR-034), write the **`pack_roles`** sidecar, set
   status `active`, invalidate the resolver cache.

Re-running commit is a **no-op** once the pack is active/deprecated. The pack is now live for triage.

---

## 5. The 7-stage validator (what "validated" proves)

Runs at assemble (dry-run, staged overlay) and at commit/activate (real repos). Findings are
`{code, severity, stage, element_id?, path?, message}`; **`ok = no error-severity findings`** — warnings/info
never block. Activation re-validates (defense in depth).

| Stage | Checks (representative codes) |
|---|---|
| 1 · BPMN | parse (class A) + classification (class B) + **compilability**/profile gate (class C: balance/structure, chained gateways, task/start arity, per-construct profile refusals) + `bpmn_sha_mismatch`/`bpmn_missing` + coverage. See §11 for the exact codes. |
| 2 · Binding↔task bijection | `duplicate_binding`, `orphan_binding`, `binding_kind_mismatch`, `executor_kind_mismatch`, `unbound_task`. |
| 3 · Capability resolution | `unknown_capability`, `capability_no_version_in_range`, `capability_only_deprecated`; `capability_not_declared` (warn). |
| 4 · HITL & side-effect policy | `hitl_role_missing`, `side_effect_requires_approve_actions`, `hitl_below_capability_floor` (+ deep_agent rules). |
| 5 · Artifacts & IO | `unknown_artifact_schema`, `artifact_no_version_in_range`, `artifact_only_deprecated`, `binding_io_mismatch`, `binding_io_schema_incompatible`; `unproduced_input` / `binding_input_unproduced` (ADR-048 — real data-flow: an input must be mapped or produced upstream, **error**). |
| 6 · Gateway variables | `gateway_variable_unknown_gateway`, `gateway_variable_unproduced`, `gateway_variable_schema_missing`, `gateway_variable_not_required`; `gateway_without_variable` (warn). |
| 7 · Policies & triage | `sod_too_few_elements`, `sod_unknown_element`, `triage_rule_invalid`; `triage_rule_smoke` (info). |

---

## 6. Execution profiles & what actually runs

Amendia **ingests Full BPMN, executes Common Executable** (ADR-027 → 034). Two conformance levels form a
hierarchy checked with `>=`:

| Profile | What executes |
|---|---|
| `common_subset` | start/end, service/user tasks, exclusive gateways, conditional sequence flows. |
| `common_executable` (**default**, ADR-034) | the above **plus** parallel gateways, timers (SLA/escalation boundary + intermediate catch), error boundary events, message catch/receive + event-based gateways, embedded sub-processes, and all task kinds (`send/script/manual/businessRule`). |

- The pack's **minimum required profile is derived from its BPMN** and pinned in the resolution sidecar at
  activation. A runtime **refuses at load** any pack whose required profile exceeds its configured profile —
  clearly, with `pack_requires_profile`, not a mid-run crash. A higher runtime runs lower packs.
- **Coverage tiers** (`executable | documented | unknown`) tell you, per element, what runs vs what is
  documentation-only. Lanes, pools, message flows, and anything above the profile are `documented`.
- **Permanently-refused-for-now** constructs (see the deferred backlog) are rejected under *both* profiles:
  sub-process boundary events, timer-boundary on a *side-effectful* serviceTask
  (`bpmn_timer_boundary_side_effect_unsupported`), inline `<script>` (`bpmn_inline_script_unsupported`),
  multi-instance on a sub-process / nested multi-instance, compensation. (Native DMN, task-level multi-instance,
  cross-pack callActivity, and a timer boundary on a *read_only* serviceTask are now executable —
  ADR-036/037/038/039/040.)

**The two-layer diagram pattern:** keep a rich *reference* BPMN (all notation, for documentation) and an
*executable* projection (subset that onboards + runs). Both are valid BPMN 2.0; only the executable projection
is meant for the wizard. See §14.

---

## 7. The two entry points (same chain)

- **The wizard** (interactive, owner-gated) — the `OnboardingSession` state machine above.
- **The seeder** (`python -m app.seeding.onboard_seed`, or startup auto-seed) — idempotent; runs the identical
  ordered chain (schemas → capabilities → manifest → BPMN → validate → activate); skips already-registered
  same-version rows; no-ops if the pack is already active. This is how `wire-repair-standard` is seeded and how
  you'd re-seed after a change (which requires resetting the DB, since active packs are immutable).

Both drive the **same backend logic** — the wizard is not a special path.

---

## 8. What happens after activation

- **Immutability:** the version is frozen. Fixes = a **new version** (or reset the DB and re-seed in dev).
- **Triage → dispatch:** an inbound exception hits `/resolve`; the matching active pack's rule pins a
  `pack_version`; the ingestor dispatches; the agent-runtime **loads the pinned pack** (profile guard applies),
  compiles the BPMN + manifest to a graph, and executes — pausing at HITL gates.
- **Sidecars:** the **resolution** sidecar (`GET /packs/{k}/{v}/resolution`) holds the pins +
  `required_execution_profile`; the **validation report** sidecar holds the last report; the **pack_roles**
  sidecar names the pack's roles.
- **Deprecate:** `active → deprecated` finishes in-flight instances but accepts no new ones.

---

## 9. Roles a pack references

Roles are **pack-local**: derived from the bindings' `hitl.role` / human `executor.role`, optionally named via
`role_meta`. Once the pack is active, its role ids surface (deduped across packs) in `GET /roles` and therefore
in the admin **Assign role** picker automatically (ADR-026) — **no code change**. But a pack only *contributes*
role ids; **a platform admin still separately grants** them to users in the identity service, and the runtime
enforces `task.role ∈ actor_roles` at claim/decide plus **SoD** (per-instance, from who actually acted). Reuse
existing role ids (e.g. `role.payments.ops_analyst`) so already-provisioned users can act without a new grant.

---

## 10. Capabilities & artifacts — the dependencies you onboard first

**Capability descriptor** (registered before any pack references it): `capability_id` (`cap.<domain>.<name>`),
`version`, `kind` (`skill | mcp | llm | deep_agent | decision | reduce`), **`side_effect`** (`read_only | side_effectful`
— policy: side-effectful ⇒ binding ≥ `approve_actions`), `idempotent?`, typed `inputs`/`outputs`, `runtime`
(per kind; the `mcp` variant is **self-descriptive**, ADR-024 — `endpoint`/`tools`/`transport`/`headers`, no
secrets), `constraints.min_hitl_mode?` (a floor bindings may tighten, never loosen), `status`. In onboarding
you **create `mcp`** ones (from introspection) and **reuse** the rest.

**`kind: decision` — native DMN (ADR-037).** A `businessRuleTask` may bind a `decision` capability whose
`runtime` carries an **inline decision table** (normalized JSON, pinned like any capability — no separate DMN
registry): `{hit_policy, inputs:[{expression}], outputs:[{name}], rules:[{when:[…], then:[…]}]}`. The table
maps typed input artifact fields to a **verdict artifact** through a bounded FEEL surface — per-cell unary
tests (`"lit"` / `42` / `true`, `< <= > >= =`, ranges `[a..b] (a..b] [a..b) (a..b)`, enums `"A","B"`,
`not(…)`, dash `-`) — and a hit policy (`UNIQUE` default, `FIRST`, `PRIORITY`, `ANY`, `COLLECT`). `side_effect`
is always `read_only`. Native DMN is **opt-in**: a `businessRuleTask` bound to a plain capability is unchanged.
**Authorable in the wizard (ADR-046):** the Capabilities step has a **decision-table builder** — the operator
defines the input/output columns, hit policy and rules as a grid (no code), the table is live-validated by the
shared `dmn` checks, and its **verdict artifact is inferred** (each output column → a required, gateway-branchable
field; literal string columns → an enum). Previously a decision capability had to be pre-seeded.

**`kind: reduce` — collection reduction (ADR-038).** Collapses a **list** input artifact into a scalar/summary
output a gateway can branch on — the answer to "is *any* party a hit?" over a multi-instance `COLLECT`/list.
Binds an ordinary `serviceTask`; `runtime.config` (inline, pinned): `{op, source?, item_path?, predicate?,
output_field}`. `op` ∈ quantifiers (`any`/`all`/`none`), `count`, numeric (`sum`/`min`/`max`/`avg`), positional
(`first`/`last`); the per-item `predicate` reuses the **bounded DMN unary-test surface**. `side_effect` is
always `read_only`. Note: gateways compare string literals (`expr.py`), so a gateway branches on a **string**
reduce output — use `first`/`last` (with an `item_path` string field); the boolean/numeric ops feed
capabilities, HITL, or further reducers. Canonical flow: multi-instance screen → `reduce` → gateway.
**Authorable in the wizard (ADR-046):** the Capabilities step has a **reduce builder** (source list artifact +
`item_path` + op + optional predicate + `output_field`); the config is live-validated by the shared `reduce`
checks and its **summary artifact is inferred** (the `output_field`, typed by the op).

**`call` executor — cross-pack composition (ADR-039).** A `callActivity` binds a `call` executor that invokes
**another pack** as a reusable sub-process, inline-compiled into the caller (one instance, one audit trail):
`{type:"call", pack:"<callee_pack_key>", version:"<range>", input_map:{callee_input: <caller dotpath>},
output_map:{caller_artifact: <callee_output>}}`. The BPMN `callActivity` carries `calledElement="<pack_key>"`
(+ optional `amendia:calledVersion`). The callee is pinned to an exact `pack_key@version` at activation
(**activate the callee first** — it must be `active`), and the composite pack's required profile is the max of
caller + callee. The callee's own HITL/SoD run in the caller instance; its artifacts are namespace-scoped so
they never collide. Cycles and excess nesting depth are refused.

**Compensation handler — a bound undo capability (ADR-043).** A compensation handler is **not** a new
capability kind: it is an ordinary activity bound to a **side-effectful** capability that *reverses* a prior
action (a `reverse_release`, `reverse_debit`, …), marked `isForCompensation="true"` in the BPMN so it sits
**off the sequence flow**. Pair it to its compensable primary with a compensation `boundaryEvent`
(`compensateEventDefinition`, `attachedToRef` = the primary) + an `<association>` (boundary → handler); a
**compensate throw** event then undoes the scope's completed compensable activities in reverse order. The
handler still needs its own binding (like any task) and runs through its **HITL gate** — compensation of a
real payment pauses for approval per handler. The **primary must be side-effectful** (there is nothing to undo
on a read-only step). Undo authorization is per-handler this cut (a batch "authorize all compensations" gate is
a future refinement).

**Artifact schema** (typed object a step reads/writes; gateways branch on its fields; HITL renders it):
`artifact_key` (`art.<domain>.<name>`), `version`, `json_schema` (**draft 2020-12**, root `object`, canonical
`$id`, `additionalProperties:false` recommended, `$ref` only to *registered* schemas), `compatibility`
(`backward` default — the registry diff-rejects breaking minors), `status`. **A field used as a gateway
variable must be `required`** (stage 6). The runtime validates every artifact **write** against the pinned
schema — malformed writes fail the task, never silently coerce.

---

## 11. Finding-code catalog (errors vs warnings)

*Reconciled against the code 2026-07-18 (`amendia_bpmn/{parser,compilability}.py`,
`process-registry/app/validation/{report,pack_validator,bpmn}.py`). `Severity ∈ {error, warning, info}`;
`ok = no error-severity findings` — warnings/info never block.*

**A · BPMN well-formedness — parser (always errors):** `bpmn_parse_error`, `bpmn_process_not_found`,
`bpmn_dangling_flow`, `bpmn_start_event_count`, `bpmn_no_end_event`, `bpmn_unreachable_node`,
`bpmn_no_path_to_end`, `bpmn_conditionless_exclusive_flow`, `bpmn_parallel_flow_condition`,
`bpmn_subprocess_start_count`, `bpmn_subprocess_no_end`, `bpmn_subprocess_arity`,
`bpmn_compensation_boundary_unwired` (ADR-043 — a compensation boundary with no `<association>` to a bound
handler). Registry adapter (`bpmn.py` / stage 1): `bpmn_sha_mismatch`, `bpmn_missing`.

**B · BPMN classification — parser (never block):** `bpmn_documented_element` (**warning** — valid BPMN
outside the executable set), `bpmn_unknown_element` (**info** — unrecognized element).

**C · Compilability / profile gate — `compilability.py` (errors).** Three kinds:
- *Refused only under a lower profile than the construct needs* — fine under `common_executable` (the
  default), an error under `common_subset`: `bpmn_parallel_gateway_unsupported`, `bpmn_timer_unsupported`,
  `bpmn_error_boundary_unsupported`, `bpmn_message_unsupported`, `bpmn_subprocess_unsupported`,
  `bpmn_task_kind_unsupported`, `bpmn_multi_instance_unsupported`, `bpmn_call_activity_unsupported`.
- *Permanently deferred* — an error under **both** profiles (see the deferred backlog):
  `bpmn_subprocess_boundary_unsupported`,
  `bpmn_inline_script_unsupported`, `bpmn_parallel_nested_unsupported`,
  `bpmn_multi_instance_subprocess_unsupported`, `bpmn_multi_instance_nested_unsupported`,
  `bpmn_call_activity_no_target`, `bpmn_call_activity_multi_instance_unsupported`, `bpmn_call_activity_cycle`,
  `bpmn_call_activity_depth`, `bpmn_event_subprocess_unsupported` (an event sub-process whose start is
  *message/signal/escalation* or *non-interrupting* — only interrupting error/timer starts run this cut,
  ADR-042); **compensation** deferred variants (ADR-043) `bpmn_compensation_transaction_unsupported`
  (transaction/`cancelEventDefinition` auto-compensation), `bpmn_compensation_targeted_unsupported`
  (`activityRef` on the throw — this cut is scope-wide), `bpmn_compensation_multi_instance_unsupported`.
- *Structural malformation* — an error even under the supporting profile: `bpmn_chained_gateway_unsupported`,
  `bpmn_task_outgoing_arity`, `bpmn_start_outgoing_arity`, `bpmn_parallel_unbalanced`,
  `bpmn_parallel_unstructured`, `bpmn_event_gateway_no_arms`, `bpmn_event_gateway_arm_not_catch`,
  `bpmn_error_boundary_ambiguous`, `bpmn_event_subprocess_ambiguous` (two event sub-processes with the same
  trigger on one scope — a duplicate timer handler, or two error handlers catching the same code, ADR-042),
  `bpmn_multi_instance_unbounded`,
  `bpmn_timer_boundary_host_unsupported` (a timer boundary on a host that is neither a HITL gate nor an
  autonomous capability serviceTask — ADR-040 retired it for the capability serviceTask case).

**D · Cross-contract validator — `pack_validator.py`, stages 2–7 (errors):** `unknown_id` (a referenced id
isn't in the BPMN — used across stages); **stage 2** `duplicate_binding`, `orphan_binding`,
`binding_kind_mismatch`, `executor_kind_mismatch`, `unbound_task`; **stage 3** `unknown_capability`,
`capability_no_version_in_range`, `capability_only_deprecated` (plus the onboarding **Capabilities-step**
guardrail `capability_id_collision` — a staged id already active in the catalog); **stage 4** `hitl_role_missing`,
`side_effect_requires_approve_actions`, `hitl_below_capability_floor`, `bpmn_timer_boundary_side_effect_unsupported`
(ADR-040 — a timer boundary on a serviceTask bound to a *side-effectful* capability; only read_only may
self-cancel a running task), `bpmn_subprocess_boundary_side_effect_unsupported` + `bpmn_subprocess_timer_scope_hitl_unsupported`
(ADR-041/042 — an interrupting-timer scope, whether a subProcess *or* the whole process under a process-level
timer event sub-process, may contain only autonomous read_only tasks; a side-effectful or HITL task inside it
is refused — the event sub-process body/handler is excluded), `bpmn_compensation_handler_not_side_effect`
(ADR-043 — a compensable primary must be side-effectful; undoing a read-only step is meaningless) +
`bpmn_compensation_handler_unbound` (an `isForCompensation` handler with no capability binding); **stage 5**
`unknown_artifact_schema`,
`artifact_no_version_in_range`, `artifact_only_deprecated`, `binding_io_mismatch`,
`binding_io_schema_incompatible`, `unproduced_input` (ADR-048 — an input neither mapped nor produced upstream;
now an **error**), `binding_input_unproduced` (ADR-048 — an `input_map` referencing an unproduced artifact);
**stage 6** `gateway_variable_unknown_gateway`, `gateway_variable_unproduced`,
`gateway_variable_schema_missing`, `gateway_variable_not_required`; **native DMN** (ADR-037, decision-kind
bindings) `dmn_table_malformed`, `dmn_unknown_hit_policy`, `dmn_bad_unary_test`, `dmn_input_unresolved`,
`dmn_output_unmapped`, `dmn_rules_overlap`; **collection reduction** (ADR-038, reduce-kind bindings)
`reduce_unknown_op`, `reduce_bad_predicate`, `reduce_predicate_required`, `reduce_source_missing`,
`reduce_output_unmapped`, `reduce_numeric_type`; **cross-pack composition** (ADR-039, call-kind bindings)
`call_activity_pack_unresolved`, `call_activity_io_unmapped`, `call_activity_io_mismatch`,
`call_activity_profile_exceeds`; **stage 7** `sod_too_few_elements`, `sod_unknown_element`,
`triage_rule_invalid`.

**E · Warnings / info (never block):** `capability_not_declared` (warn, stage 3),
`gateway_without_variable` (warn, stage 6), `decision_ref_mismatch` (warn — advisory `businessRuleTask`
`decisionRef` names a different table id, ADR-037), `bpmn_compensate_throw_no_handlers` (warn — a compensate
throw whose scope has no compensable activities; a runtime no-op, ADR-043), `triage_rule_smoke` (info, stage 7)
— plus the two class-B BPMN classification findings.

**F · Runtime load (agent-runtime, not the registry validator):** `pack_requires_profile` — the runtime
refuses a pack whose pinned `required_execution_profile` exceeds the runtime's configured profile.

---

## 12. BPMN element support matrix

**Bindable-in-wizard now matches executable (ADR-044).** Every executable element below that binds an executor
(the full task set + message catch/receive + callActivity + nested sub-process tasks + `isForCompensation`
handlers) is authored in the onboarding **Bindings** step (§4) — single fidelity, the reference diagram is the
executable one, no projection. The `subProcess` / event-subprocess **containers** are structural (never bound);
the **Refused** row stays refused, surfaced at the assemble dry-run via the existing codes.

| Element | Status (default `common_executable`) |
|---|---|
| startEvent, endEvent, serviceTask, userTask, exclusiveGateway, conditional sequenceFlow | **Executable** (also `common_subset`) |
| parallelGateway (balanced, block-structured) | **Executable** |
| timerBoundaryEvent on a userTask (idle-gate SLA/escalation) or on a **read_only serviceTask** (in-process running-deadline / cooperative cancellation — ADR-040), timerIntermediateCatchEvent | **Executable** |
| errorBoundaryEvent on a serviceTask (modeled rejection) | **Executable** |
| messageIntermediateCatchEvent, receiveTask, eventBasedGateway (message/timer) | **Executable** |
| embedded subProcess (nested) | **Executable** (inlined) |
| timer boundary on a subProcess (scope-wide SLA / cancellation) or error boundary on a subProcess (scope error handler, nested inner→outer) — ADR-041 | **Executable** (projected onto inner nodes) |
| event subProcess (`triggeredByEvent="true"`) with an interrupting **error** or **timer** start — a scope-wide handler at **process level** or nested in a subProcess; on trigger the enclosing scope is cancelled and the ESP body runs (inlined) — ADR-042 | **Executable** (handler = scope boundary on the enclosing scope; body inlined) |
| **compensation** — a compensable side-effectful serviceTask with a compensation `boundaryEvent` (+ `<association>`) paired to an `isForCompensation` **undo handler**, and a **compensate throw** (`compensateEventDefinition` on an intermediate/end event) that undoes the scope's completed compensable activities in **reverse (LIFO) order**, each through its HITL gate, exactly once — ADR-043 | **Executable** (off-flow handler inlined; throw = self-looping LIFO driver) |
| multiInstanceLoopCharacteristics on a task (parallel + sequential; `amendia:aggregation` list/indexed) | **Executable** |
| callActivity (cross-pack composition — inline-compiled; `calledElement`+`amendia:calledVersion`; input_map/output_map — ADR-039) | **Executable** (inlined) |
| sendTask, scriptTask (bound to a capability), manualTask, businessRuleTask (bound capability, or a native DMN `decision` capability — ADR-037, now **authorable as a table in the wizard** — ADR-046) | **Executable** |
| lanes, pools/participants, message flows, textAnnotation, dataObject/Store | **Documented** (not executed; used for inference/coverage) |
| *message/signal/escalation* boundary events on a subProcess (timer + error are executable, ADR-041) or a callActivity (`bpmn_subprocess_boundary_unsupported`), timer-boundary on a *side-effectful* serviceTask (`bpmn_timer_boundary_side_effect_unsupported` — read_only is executable, ADR-040), a *side-effectful* or *HITL* task inside an interrupting-timer subProcess *or* process scope (`bpmn_subprocess_boundary_side_effect_unsupported` / `bpmn_subprocess_timer_scope_hitl_unsupported`, ADR-041/042), a *message/signal/escalation-triggered* or *non-interrupting* event sub-process, or two same-trigger event sub-processes on one scope (`bpmn_event_subprocess_unsupported` / `bpmn_event_subprocess_ambiguous` — interrupting error/timer ESPs are executable, ADR-042), inline `<script>` (`bpmn_inline_script_unsupported`), nested parallel (`bpmn_parallel_nested_unsupported`), multi-instance on a sub-process (`bpmn_multi_instance_subprocess_unsupported`), nested multi-instance (`bpmn_multi_instance_nested_unsupported`), callActivity as a multi-instance host / boundary-on-callActivity / nested-instance callee (ADR-039 stretches), **transaction/cancel auto-compensation**, **targeted** (`activityRef`) or **multi-instance** compensation (`bpmn_compensation_transaction_unsupported` / `_targeted_unsupported` / `_multi_instance_unsupported` — explicit scope-wide compensation IS executable, ADR-043), ad-hoc sub-process, signal/escalation events, message/timer start events | **Refused under both profiles** (deferred — see `amendia_bpmn_deferred_backlog.md`) |
| anything else | **Unknown** (info; retained for coverage) |

---

## 13. Troubleshooting & common gotchas

- **"BPMN rejected" with many `bpmn_unsupported`/dangling errors:** you uploaded the *reference* (full-notation)
  diagram, not the *executable* projection — or a non-executable construct sits on the live sequence-flow path.
  Upload the executable file (§6, §14).
- **Side-effectful capability won't accept my HITL mode:** the guard forces ≥ `approve_actions`
  (`side_effect_requires_approve_actions`) — the UI greys weaker modes. Set the gate, or reclassify the
  capability `read_only` if it genuinely has no side effect.
- **`gateway_variable_not_required`:** the field the gateway branches on must be **`required`** in its
  producing artifact schema (a gateway can't branch on possibly-absent data). Fix the schema (new artifact
  version) or the variable.
- **`unbound_task` / bijection errors:** every service/user/message task (including nested sub-process tasks)
  needs exactly one binding; the `subProcess` container itself is **not** bound.
- **Pack activates but fails at runtime with `pack_requires_profile`:** the deployment's runtime runs a lower
  profile than the pack needs. Run the runtime at `common_executable` (default) or remove the richer construct.
- **Two packs fight over the same exception:** triage priority collision — lowest priority wins. Scope your
  rule (distinct reason code or a winning priority).
- **Non-compliant MCP tool can't be selected:** it's missing `outputSchema` / has a non-object root / an
  external `$ref`. Fix the server per the MCP Implementor Guideline.
- **Can't re-onboard the same version:** it's immutable once active. Bump the version (or, in dev, reset the DB
  and re-seed).
- **Reused capability rejected at commit:** it must be `active` and satisfy the range *at commit time*
  (re-checked). A deprecated/removed version fails.

---

## 14. Worked example (wire-repair-agentic)

The `wire-repair-agentic` kit (`wire-repair-agentic-onboarding-kit.md`) walks the full flow with real payloads:
new domain `wirefix` (so it never collides with the seeded `cap.payment.*`), ten MCP tools on a dumb server
(three side-effectful → `approve_actions`, sanctions with an `approve_result` floor), a triage rule scoped to a
test reason code (to avoid colliding with the seeded pack), SoD on the two four-eyes pairs, and gateway
variable `beneficiary.repair_verdict` (which is why the assess tool's output schema marks `repair_verdict`
**required**). The **two-layer** diagrams (`wire-repair-agentic.reference.bpmn` full notation vs
`wire-repair-agentic.bpmn` executable) show exactly what onboards vs what documents.

---

## 15. Glossary

**ProcessPack** — versioned onboarding bundle (BPMN + manifest + dependencies). **Manifest** — execution
metadata; the source of truth for what runs. **Binding** — per-task execution config. **Capability** —
registered unit of agent competence (skill/mcp/llm/deep_agent). **Artifact / artifact schema** — a typed state
object and its registered JSON Schema. **Triage** — matching an exception to a pack via predicate rules.
**Pin** — an exact version resolved from a range at activation. **HITL** — human-in-the-loop; the four gate
modes. **SoD** — separation of duties (four-eyes). **OnboardingSession** — the backend state machine behind the
wizard. **Coverage tier** — `executable | documented | unknown` per BPMN element. **Execution profile** —
`common_subset | common_executable`; the pack's required level is derived + pinned; the runtime enforces `>=`.
**Resolution sidecar** — the registry's pins + required profile written at activation.

---

*Maintainers: this is a living document. When a backlog item ships (a new executable construct, a new binding
kind, a new finding code, a profile change), update §4–§6, §11–§13 and note the ADR. Keep it the single,
authoritative "how to onboard a process" reference.*
