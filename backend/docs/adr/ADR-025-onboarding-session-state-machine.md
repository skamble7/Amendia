# ADR-025 — Form-driven onboarding: the `OnboardingSession` state machine + MCP tool→capability inference

- **Status:** Accepted
- **Date:** 2026-07-15
- **Related:** ADR-010 (process-registry v1 — explicitly **deferred the "onboarding UI"**; this ADR delivers
  it), ADR-024 (self-descriptive `mcp` runtime — the shape each inferred capability targets), ADR-021
  (`deep_agent` kind — reuse-only here), ADR-016 (secret-refs in `headers`); `amendia_platform_contracts_v1.md`
  (the five contracts + 7-stage validation matrix), `amendia_contracts_reference.md` (§2.4 HITL ordering,
  §9 interlock), `backend/services/process-registry/README.md`, `webui/src/features/registry/OnboardingWizard.tsx`.
- **Advances:** the deferred "onboarding UI" item from ADR-010.

## Context

Onboarding a ProcessPack meant hand-authoring a manifest JSON and chaining four stateless registry calls
(`POST /packs` → `PUT …/bpmn` → `POST …/validate` → `POST …/activate`). The webui wizard was a thin veneer
over that: it pasted raw manifest JSON, assembled it client-side, and drove the four calls. Two problems:

- **Assembly logic lived in the browser.** Ordering, id conventions, artifact/binding wiring — all in the
  SPA, none reusable by other callers, none tested at the contract boundary.
- **No way to author capabilities from forms.** A bank operator standing up a pack against a running MCP
  server had to know the MCP tool's schemas, hand-write two artifact schema registrations and one `kind: mcp`
  capability descriptor (with the correct canonical `$id`s, `additionalProperties: false`, etc.), register
  them, then reference them from the manifest. Error-prone and JSON-heavy.

ADR-010 left "onboarding UI" out of scope precisely because the registry was a stateless CRUD pipeline with
nowhere to hold the half-authored pack. The maintainer's requirement: move **all** authoring logic into the
backend as a **stateful session**, make the frontend a thin renderer, and add first-class **MCP
introspection → capability inference** so an operator can point at a running MCP server and pick tools.

## Decision

### Part A — the `OnboardingSession` aggregate (process-registry)

A new registry-owned **authoring scratch space** — collection `onboarding_sessions`, keyed by `session_id`,
owner-scoped by the Amendia `usr-…` from the bearer. It is **not a contract document**: it accumulates
*staged* pieces and carries an explicit state. Distinct from the pack lifecycle (`draft → validated → active
→ deprecated`) — **the pack does not exist until commit**.

**State machine** (one transition per endpoint; each guards ordering and returns the full updated session):

| State | Endpoint (owner-gated) | Effect |
|---|---|---|
| `initiated` | `POST /onboarding` | Store basics. 409 if the `pack_key@version` already exists as an active/deprecated pack. |
| `bpmn_attached` | `PUT /onboarding/{id}/bpmn` | Parse BPMN (`amendia_bpmn`), derive inventory. Onboarding is **stricter** than the runtime parser: exclusive gateways only (reject parallel + gateway-to-gateway chaining) with clear findings. |
| `capabilities_resolved` | `POST /onboarding/{id}/capabilities` | Stage new `mcp` capabilities (+ two inferred artifacts each) and record reused catalog refs. |
| `bindings_set` | `PUT /onboarding/{id}/bindings` | Store bindings; check the task↔binding **bijection**; enforce the **side-effect→HITL** coupling. |
| `triage_set` | `PUT /onboarding/{id}/triage` | Store triage predicate trees (validated as `Predicate`). |
| `policies_set` | `PUT /onboarding/{id}/policies` | Store gateway variables, SoD, pack-local roles. |
| `assembled` | `POST /onboarding/{id}/assemble` | Compose the full manifest; **dry-run** the real 7-stage validator against staged (not-yet-registered) rows; return the report. |
| `completed` | `POST /onboarding/{id}/commit` | Run the real ordered, idempotent chain. |

Plus `GET /onboarding` (list this owner's sessions), `GET /onboarding/{id}` (resume), `DELETE /onboarding/{id}`
(abandon — safe, nothing was written to the contract collections).

Four design commitments make this reuse the existing engine rather than fork it:

1. **Staging, not writing.** New artifacts/capabilities live *inside the session* and are written to
   `artifact_schemas` / `capabilities` only at commit. Reused capabilities are stored as refs, validated to
   exist + be active at stage time **and re-checked at commit**. This keeps immutable rows from being
   orphaned when an operator abandons.
2. **Dry-run overlay.** `assemble` composes a `ProcessPackManifest` and runs the **unchanged** `PackValidator`
   through tiny read-only overlays that surface staged artifacts/capabilities as if active — so the operator
   sees all 7 stages (incl. gateway-variable-resolves-to-a-required-field) *before* anything is registered.
3. **Idempotent commit chain = the seeder's order.** `commit` reuses `register_schema`, `cap_repo.insert`,
   `pack_repo.insert`, `bpmn_repo.upsert`/`set_bpmn_sha`, `PackValidator.validate`, `resolve_pins`,
   `pack_repo.activate` — exactly the `app.seeding.onboard_seed` sequence. `409 already-exists ⇒ done` at each
   step; a non-clean real validation **stops before activate** and leaves the session at `assembled`; a
   re-run is a no-op (short-circuits when the pack is already active). Per-item `commit_progress` is recorded
   for a resumable, renderable chain.
4. **Invalidation cascade.** Editing an upstream step resets dependent downstream state and reports **which
   data was cleared** (`last_cleared`) so the UI can explain it. Re-attaching BPMN clears bindings / gateway
   variables / SoD and re-derives inventory; re-staging capabilities clears bindings + gateway variables; any
   staged-data change drops the dry-run.

### Part B — MCP introspection + inference (`POST /capabilities/introspect-mcp`)

Owner-gated. Connects to an operator-supplied MCP server as a **client** over the given transport (default
`streamable_http`), handshakes, calls `tools/list`, and returns each tool with a **compliance verdict**. The
client is an **injectable** `McpIntrospector` (real impl uses the official `mcp` SDK, **lazily imported** and
timeout-bounded; a fake/in-memory client is injected in tests — no live network in CI).

**Compliance (MCP Implementor Guideline):** a tool missing `outputSchema`, with a non-object schema root, or
carrying an **external `$ref`** is `non_compliant` (with reasons) and **cannot be selected**.

**Inference** (applied when the operator selects tools) turns each compliant tool into:

- an **input artifact schema** — take `inputSchema`, force root `type: object`, set `$schema` to draft
  2020-12, inject the canonical `$id`
  (`https://amendia.dev/schemas/artifacts/<domain>/<name>/<version>.json`), default
  `additionalProperties: false` (warn if the source was open), reject external `$ref`s. Suggested key
  `art.<domain>.<tool>_input`, all **operator-editable**.
- an **output artifact schema** — same treatment on `outputSchema`.
- one **`kind: mcp` capability descriptor** — `runtime: {kind: mcp, endpoint, tools:[tool], transport,
  headers}` (ADR-024 shape), `inputs`/`outputs` referencing the two staged artifacts, operator-supplied
  `side_effect` (default `read_only`) and `idempotent`.

`<domain>` seeds from the session default (per-item editable); `<name>` is the tool name sanitized to
`[a-z0-9_]`. **Creation is MCP-only** — `skill`/`llm`/`deep_agent` are **reuse-only** from the catalog.

**SSRF posture:** the endpoint is operator-supplied, so this is owner-gated, `http(s)`-scheme-restricted, and
timeout-bounded; response bodies are never echoed beyond the tool schemas. Deployments may layer a stricter
egress allowlist.

### Part C — enforced invariants (fail early, in the relevant step)

- **Bijection** — exactly one binding per BPMN service/user task, no orphans/duplicates, `element_kind` and
  executor-kind (serviceTask→capability, userTask→human) checked — at `bindings_set`, with field-level errors.
- **Side-effect → HITL coupling** — a binding to a `side_effectful` capability must be ≥ `approve_actions`; a
  binding to any capability must be ≥ its `min_hitl_mode`. Rejected at `bindings_set` with `allowed_min_mode`
  so the UI greys out weaker modes.
- **Non-`none` HITL requires a role.** Roles are **pack-local** (collected from `policies_set` + the bindings;
  no cross-pack role catalog). User↔role assignment stays the identity service's job.
- **Gateway variables** resolve to a `required` field of an upstream-produced artifact — already a validator
  stage, surfaced in the dry-run.

### Part D — thin frontend (webui)

The Registry → "Onboard process pack" wizard is rewritten to hold **no manifest-assembly logic**: it
creates/loads a session (resumable by id), renders the 7-step stepper and each form **from the session state
the backend returns**, POSTs each step and re-renders from the response, shows **server-side field errors**
inline, reflects the invalidation cascade, and — on the Capabilities step — introspects the MCP server and
lets the operator pick compliant tools + edit inferred ids. Built in the existing shadcn/Tailwind design
system (the rest of the app is unchanged).

## Consequences

- **All authoring logic is server-side and tested at the contract boundary.** The webui is a renderer; other
  clients (CLI, scripts) can drive the same state machine.
- **Immutability respected.** Registered artifacts/capabilities and activated packs are immutable; the whole
  design defers every write to `commit` precisely so an abandoned session leaves no orphaned rows.
- **Resumable + idempotent.** A session survives a reload; the commit chain resumes after a partial failure
  and a full re-run is a no-op.
- **Env-specific endpoint inherited from ADR-024.** An inferred `mcp` capability pins one deployment's MCP
  `endpoint`; bump the version to change it (don't hand-edit an onboarded descriptor).
- **New dependency.** process-registry gains `mcp` (the MCP client). It is **lazily imported** so the module
  and the test suite (which injects a fake introspector) run without it — but a running service needs a
  `uv sync` before real introspection works.
- **No validator/parser/activation change.** The 7-stage validator, `amendia_bpmn`, `resolve_pins` and the
  seeder are reused verbatim; the dry-run overlay is the only new adapter over them.

## Traps recorded for maintainers

1. **The dry-run overlay only surfaces staged rows as *active*; it does not write them.** Nothing hits
   `artifact_schemas` / `capabilities` until `commit`. Don't "optimise" by registering early — it reintroduces
   the orphaned-immutable-row problem the staging design avoids.
2. **`commit` re-validates against the *real* repos and stops before activate on any error.** The dry-run at
   `assemble` is advisory; a clean dry-run is not a guarantee (the catalog can change between assemble and
   commit). Never skip the commit-time validation.
3. **Onboarding BPMN strictness > runtime parser.** `amendia_bpmn` tolerates parallel gateways; onboarding
   rejects them (and gateway-to-gateway chains). If you relax this, do it here, not in the shared parser.
4. **MCP endpoint is untrusted input.** Keep the introspection client injectable, timeout-bounded, and
   owner-gated; never echo server responses beyond the tool schemas. Tests must use the fake client.
5. **Capability *creation* is `mcp`-only in this flow.** Other kinds are reuse-only. Don't add
   skill/llm/deep_agent authoring here — those are separate, deliberate acts.
