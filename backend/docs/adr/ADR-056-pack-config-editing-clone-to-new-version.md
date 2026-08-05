# ADR-056 — Pack editing is clone-to-new-version of the config layer (BPMN out of scope)

**Status:** Accepted (2026-08-01)
**Related:** ADR-052 (business-facing onboarding), ADR-054 (stepped pre-filled review), ADR-025 (onboarding
session state machine), ADR-049/050/051 (trigger, human-authored artifacts, nameable outputs). Registry resolver +
pack lifecycle (`draft → validated → active → deprecated`).

## Context

Onboarding produces an immutable, versioned `ProcessPack` (`pack_key@version`) and activates it. There is no path
to change an activated pack: the only options today are re-onboarding from scratch (losing the review work) or
editing Mongo by hand (unvalidated, dangerous). Yet real needs surfaced repeatedly — repoint a binding source (the
`Screen ← approved_repair.party` coupling), fix a mis-bound capability, adjust a HITL role, refine a human-artifact
schema, tweak triage.

Two facts shape the solution:

1. **The runtime loads a pack bundle by `(pack_key, version)` and running instances are pinned to their version.**
   Mutating an active version's config in place would change what an already-running instance executes on its next
   segment (e.g. a HITL role changing mid-instance). So in-place editing of an active pack is unsafe, by design.
2. **The registry already supports coexisting versions and version-preferring routing.** `ResolveService.resolve`
   evaluates triage across all *active* packs and, on ties, sorts `version DESC` — the highest active version of a
   matching `pack_key` wins. `activate` doesn't touch sibling versions; `(pack_key, version)` is unique;
   `list_versions` exists.

Amendia's role is **process execution**, not diagram authoring. BPMN structure/flow/timer editing belongs to
dedicated BPMN tools; Amendia edits only the execution **config** it layers on a fixed diagram.

## Decision

1. **Editing a pack = cloning the active version into a new (bumped) version of the config layer, over an
   UNCHANGED BPMN.** "Edit" hydrates the active pack into an onboarding session (reverse of assemble), opens the
   ADR-054 stepped review pre-filled from the pack, and the operator edits config — bindings (executor/tool, HITL
   mode+role, input-map sources, output names), human-artifact schemas (refiner), trigger+triage, gateway
   conditions/source artifacts + SoD, role labels/descriptions — then re-validates and publishes as a new version.
   The BPMN and its `bpmn_sha256` are invariant across an edit.

2. **BPMN editing is out of scope.** Structure, flow, and timer-duration changes require a new diagram authored in a
   BPMN tool, brought in via re-onboarding. Amendia never mutates the diagram.

3. **Publishing auto-deprecates the prior active version of the same `pack_key`** — one live version per process.
   Running instances stay pinned to their (immutable) version and are unaffected; the resolver routes new events to
   the live version. No routing changes are needed — version-preferring resolution already does this.

4. **Rollback is first-class:** re-activate an older version and deprecate the current one (making the older version
   live). Exposed in the registry alongside a per-`pack_key` version history.

5. **Always a new version** — even for a pack with no running instances. No in-place special case; the unused prior
   version is harmless and auto-deprecated on publish.

## Consequences

- **+** In-flight instances are never disrupted by an edit (pinned to their immutable version).
- **+** Reuses the entire ADR-054 stepped review, refiner, reconcile/validator, activate, and schema
  version-bump-on-change — the only new backend piece is manifest→session hydration.
- **+** No new routing/"current version" infrastructure — the resolver's version-desc tiebreak + auto-deprecate is
  the pointer; rollback is just re-activate-old + deprecate-new.
- **+** Fixes every config edit encountered in practice without a re-onboard.
- **−** Version proliferation over time (mitigated: prior versions auto-deprecate; history view + rollback).
- **−** Cross-version migration of *running* instances is not offered (explicit non-goal — a migrated in-flight
  execution is a much harder, separate problem).

## Non-goals

- BPMN structure/flow/timer editing (use a BPMN tool + re-onboard).
- Migrating in-flight instances across pack versions.
- In-place mutation of an active pack.
