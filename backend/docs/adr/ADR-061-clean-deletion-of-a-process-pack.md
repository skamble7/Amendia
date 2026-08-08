# ADR-061 — Clean deletion of a process pack (version or whole pack)

**Status:** Proposed — 2026-08-07
**Date:** 2026-08-07
**Context owner:** Sandeep Kamble
**Depends on:** ADR-060 (pack-owned capabilities & schemas — the precondition that makes this a clean cascade).
**Relates:** ADR-058 Phase B (`PackLifecycleEvent`/`PackLifecycleOp` → GLEA audit), the pack lifecycle
(`activation.py`, `packs.py`), `require_roles("role.process.owner")`.

## Context

There is no way to remove an onboarded process pack. Packs accumulate across the collections
(`process_packs`, `bpmn_documents`, `validation_reports`, `pack_resolutions`, `pack_roles`, and — after
ADR-060 — the pack-owned `capabilities` / `artifact_schemas`), plus authoring `onboarding_sessions`. Operators
need to delete either a **single pack version** or an **entire pack** (all versions), and it must be a **clean**
delete — no rows for that pack left behind in any collection, and (ADR-060) the pack's owned capabilities and
schemas removed with it.

Two invariants shape the design. **Packs are immutable:** a manifest is never edited in place; deletion is a
governed *removal*, not a mutation, so it doesn't violate immutability. **Deletion must be auditable:** the
record of who deleted what must **outlive** the deleted rows — which the existing `PackLifecycleEvent` → GLEA
path already provides, since GLEA (ClickHouse) is a separate system of record from the registry's Mongo
collections.

## Decision

### D1 — Two endpoints, process-owner only

- `DELETE /packs/{pack_key}/{version}` — delete one pack version.
- `DELETE /packs/{pack_key}` — delete every version of the pack.

Both gated by `require_roles("role.process.owner")` — **no other role**, matching every existing pack mutation.
Both return a summary of what was removed (collections touched, counts of caps/schemas/sessions purged).

### D2 — Clean cascade (enabled by ADR-060 ownership)

Deletion removes, for the target scope, **every** row keyed to it:

- **Per-version docs:** `process_packs`, `bpmn_documents`, `validation_reports`, `pack_resolutions`,
  `pack_roles` for `(pack_key, version)` — or all versions for a whole-pack delete.
- **Pack-owned catalog (ADR-060):** `capabilities` and `artifact_schemas` stamped with the target
  `(pack_key, pack_version)`. Because ownership is per pack version (ADR-060 D1), this is a **pure cascade** —
  delete every cap/schema row for that `(pack_key, pack_version)` with **no reference-counting** (nothing is
  shared across packs or versions).
- **Authoring scratch:** `onboarding_sessions` whose committed pack is the deleted `(pack_key, version)`.

A whole-pack delete is the per-version delete applied to every version, plus any pack-level-only rows.

### D3 — Audit first, then delete (survives the delete)

Extend `PackLifecycleOp` with **`DELETE = "delete"`**. Before removing rows, emit a `PackLifecycleEvent`
(`op=delete`, `actor=<owner user id>`, `detail=<scope + purge summary>`, per version for a whole-pack delete)
via the existing fail-soft `emit_pack_lifecycle`. Ordering matters: **emit the audit event first**, then
delete — so the GLEA trail is written even if the row-removal partially fails. A whole-pack delete emits one
`delete` event per version (a complete per-version trail) plus a rollup line in `detail`.

### D4 — Force-delete, any status, guarded only by audit + confirmation

Per operator decision, `DELETE` removes the pack **regardless of lifecycle status** (`draft` / `validated` /
`active` / `deprecated`) and **regardless of in-flight instances**. There is no deprecate-first requirement and
no cross-service liveness gate. The safeguards are: (a) process-owner-only, (b) the destructive-confirm in the
UI, and (c) the durable GLEA audit record. **Consequence to document loudly:** deleting an `active` pack, or one
with paused/`waiting_hitl` instances, will break those instances if they later try to resume and re-load the
(now-absent) bundle — the operator owns that call. This is recorded in the `detail` of the audit event
(status-at-delete, whether it was active).

### D5 — Ordering & idempotency (no cross-collection transaction assumed)

Mongo here is standalone (no multi-doc transactions guaranteed). Delete in an order that never leaves a
danging-but-loadable pack, and make each step idempotent so a re-run of a partial delete completes:

1. Emit the `delete` audit event(s).
2. Delete the `process_packs` manifest row(s) **first** — the pack is immediately un-loadable / un-resolvable.
3. Delete the per-version sidecars (`bpmn_documents`, `validation_reports`, `pack_resolutions`, `pack_roles`).
4. Delete the pack-owned `capabilities` / `artifact_schemas` for the scope.
5. Delete the committed `onboarding_sessions`.

Each `delete_many` is scoped by `{pack_key(, version)}` and is a no-op if already gone → the whole op is
idempotent and safe to retry.

## Consequences

- An operator (process-owner) can cleanly remove a pack version or a whole pack; nothing for that pack survives
  in any registry collection, and its owned caps/schemas go with it — no orphans, no over-deletion (guaranteed
  by ADR-060 ownership, not by fragile reference-counting).
- The deletion is permanently auditable in GLEA even though the pack rows are gone (audit-first + separate SOR).
- Force-delete is powerful and can strand in-flight instances; that risk is explicit, owner-gated, confirmed,
  and audited — an accepted trade for a dev/governance tool.
- Immutability is preserved: no manifest is ever mutated; a pack is either present or wholly removed-and-audited.

## Design calls fixed here (change in review, not in code)

1. **Force-delete any status**, no deprecate-first gate, no runtime liveness check (per D4) — safeguarded by
   role + confirm + audit.
2. **Audit-first** ordering so the GLEA record survives a partial failure (per D3/D5).
3. Whole-pack delete emits a **per-version** `delete` event (complete trail), not a single rollup event.
4. `onboarding_sessions` for the deleted pack are **purged** as part of "clean" (per D2).
