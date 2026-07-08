# ADR-010 — Process-registry service v1 (contract storage, onboarding validation, activation & resolve)

- **Status:** Accepted
- **Date:** 2026-07-08
- **Related:** `amendia_platform_contracts_v1.md` (the five contracts + validation matrix),
  `amendia_contracts_reference.md` (§2.4 HITL ordering, §9 interlock), `amendia_build_plan.md` (Step 2);
  ADR-009 (agent-runtime foundation); `backend/services/process-registry/README.md`.
- **Advances:** the "implement process-registry" item in `amendia_project_brief.md` (build plan Step 2).

## Context

The agent-runtime (ADR-009) holds the five contracts as models and reads a seeded pack, but nothing
lets a bank **author and validate** that pack: register capabilities/artifact schemas, onboard a
ProcessPack, prove the whole bundle is internally consistent, pin versions, and answer the runtime's
triage lookup. That authoring/validation engine is Step 2 of the build plan — the **process-registry**.

A registry that validated *different* shapes than the runtime executes would guarantee drift, so the
contract models had to become **shared** before building the registry.

## Decision

### Part A — shared contract models (`libs/amendia_contracts`)

Extract the six contract modules (`common`, `process_pack`, `capability`, `artifact_schema`,
`dispatch`, `hitl_task`) out of agent-runtime into a new `libs/amendia_contracts` package (alongside
`amendia_common`). Agent-runtime keeps thin **re-export shims** (`from amendia_contracts.X import *`) so
every existing import path and test is unchanged; `process_instance` stays runtime-owned. Added to the
lib: `semver.py` (a dependency-free range matcher — exact / caret with npm caret-zero rules / bounded
comparators), `VersionedRef.matches()`, and `hitl_mode_at_least()` (the documented HITL strictness
ordering the validator needs).

### Part B — the process-registry service (`:8084`, no RabbitMQ in v1)

The **authoring/write side** of the platform. Highlights:

- **Ownership split:** the registry is the **write owner** of `capabilities`, `artifact_schemas`,
  `process_packs` (the same collections/shapes the agent-runtime **reads**), plus its own
  `bpmn_documents` store. Documented in both services' READMEs; the runtime's file-seed path is retired
  in a future task.
- **The cross-contract validator** — a 7-stage pipeline producing a deterministic `ValidationReport`
  of `{code, severity: error|warning|info, element_id?, path?, message}`:
  1. **BPMN** (stdlib ElementTree): parse, one `process` matching `process_id`, sha256 match, supported
     element subset, one start, full reachability, exclusive/parallel gateway condition rules.
  2. **Bijection**: every service/user task ↔ exactly one binding; kind & executor-type consistency.
  3. **Capability resolution** (via `semver`): each ref resolves to an active version in range
     (unknown-id / no-version-in-range / only-deprecated distinguished).
  4. **HITL & side-effect policy**: `side_effectful` ⇒ hitl ≥ `approve_actions`; binding ≥ capability
     `min_hitl_mode`.
  5. **Artifacts & IO**: refs resolve to non-deprecated schemas in range; binding IO reconciles with
     capability IO (name-set + overlapping ranges); input-produced-upstream (warning).
  6. **Gateway variables**: declared per exclusive gateway; produced upstream; field `required` at every
     level of the resolved schema.
  7. **Policies & triage**: SoD elements exist; triage rules parse; smoke-test against the sample
     exception (info).
  Later stages emit `stage_skipped` when a prerequisite (a parseable BPMN) is missing.
- **Pack lifecycle**: `POST /packs` (draft) → `PUT .../bpmn` → `POST .../validate` (all-clear ⇒
  `validated`) → `POST .../activate` (pins every range to the highest active version) → `.../deprecate`.
  Versions are immutable (fix-by-new-version); a BPMN re-upload drops the pack back to `draft`. Multiple
  versions of one `pack_key` may be active simultaneously; triage priority decides.
- **Artifact-schema registration pipeline**: draft-2020-12 meta-validation → conventions (`$id` derived
  from key+version; `additionalProperties!=false` ⇒ warning) → `$ref` whitelist to registered `$id`s →
  backward-compat diff on minor/patch bumps (conservative: unknown change ⇒ breaking).
- **`POST /resolve`**: evaluates active in-scope packs' triage rules against an exception envelope,
  orders matches by priority (then pack_key, then semver-desc), returns the pinned winner or a 404
  no-match body. A 30s in-process cache is the seam for a future compiled index.
- **Seeding through the front door**: `onboard_seed.py` drives the existing seed dataset through the
  real service layer (register schemas → capabilities → submit manifest → upload BPMN → validate →
  activate). It doubles as the validator's end-to-end proof — **the seed validated all-clear with zero
  changes needed**.

## Consequences

- Onboarding is now a *validated property*: by activation, every reference is resolved, every data shape
  agreed, every human gate placed, and every version pinned — the registry side of the platform's safety
  argument (reference §9).
- Contract models are shared, so the registry validates exactly what the runtime executes; the shims keep
  agent-runtime and its 38 tests unchanged.
- **Design decision — shared collection, pure shape:** the task requires the registry and runtime to
  share the catalog collections with the *same document shapes*. Registry-only data (the validation
  report and the full activation resolution) therefore lives in **sidecar collections**
  (`validation_reports`, `pack_resolutions`) rather than as extra fields on the `process_packs` doc,
  which stays a pure manifest (with the model-native `requires_capabilities[].resolved` pins). The
  registry also tolerates the runtime's inline `bpmn_xml` on read. This keeps both services' strict
  (`extra="forbid"`) models valid against the shared docs.
- **Ownership in compose:** the registry seeds the shared catalogs through its onboarding pipeline, so
  the runtime no longer self-seeds there (`AGENTRT_SEED_ON_STARTUP=false`) — realizing "registry writes,
  runtime reads" without modifying agent-runtime code.
- **Deferred (out of scope):** onboarding UI, registry RabbitMQ events (`pack_activated`), ingestor↔
  `/resolve` wiring, the runtime switching to registry-backed lookup, BPMN execution, auth, and
  config-forge capability-config checks.
- **Open question narrowed:** triage matching is attribute-based via the declarative predicate tree
  (`all/any/not/leaf` over envelope dot-paths), evaluated identically in validation and `/resolve`.
