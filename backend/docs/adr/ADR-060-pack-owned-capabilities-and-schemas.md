# ADR-060 — Pack-owned capabilities & schemas: evict the shared catalog

**Status:** Proposed — 2026-08-07
**Date:** 2026-08-07
**Context owner:** Sandeep Kamble
**Relates:** ADR-049 (domain-neutral per-pack trigger schema; eviction of domain contracts), ADR-057
(complete input schemas), ADR-047 (platform domain-neutrality), the Process Onboarding flow
(`process-registry`), the agent-runtime bundle loader. **Enables:** ADR-061 (clean pack deletion).

## Context

The process-registry is the write-owner of three "catalog" collections — `process_packs`, `capabilities`,
`artifact_schemas` — plus per-version sidecars (`bpmn_documents`, `validation_reports`, `pack_resolutions`,
`pack_roles`). `capabilities` and `artifact_schemas` are keyed by `(capability_id, version)` /
`(artifact_key, version)` with **no owning-pack link** — a **shared, global catalog**. Onboarding avoids
cross-pack collisions only by *convention*: it derives `cap.<domain>.<tool>` ids where `<domain>` defaults to
the sanitized `pack_key` (`onboarding.py`: "so ids are process-scoped and don't collide with the active
catalog"), and it runs a cross-pack clash check against the active catalog at the Capabilities step. The
hand-authored seed reference packs break even that convention: `wire-repair-agentic` and `wire-repair-standard`
**share** `cap.payment.*` / `art.*`.

This shared catalog is a liability:

1. **No clean lifecycle.** Because a capability/schema row has no owner, you cannot answer "what does this pack
   own?" without scanning every manifest and every capability's I/O refs. Deleting a pack (ADR-061) would
   require whole-catalog reference-counting to avoid orphaning or over-deleting shared rows — fragile and
   easy to get wrong.
2. **Accidental coupling.** Two packs that onboard the same MCP server *should* be independent, but a shared
   catalog invites id collisions and silent reuse, so one pack's edit can perturb another's resolution.
3. **The domain-neutral onboarding model already treats each pack as self-contained** (ADR-049/057: a pack
   declares its own trigger and derives its capabilities/schemas from MCP introspection *at onboarding time*).
   The storage model never caught up.

Decision (Sandeep): **capabilities and schemas belong to a pack.** Each pack is self-contained; if the same MCP
server is used by two packs, each pack gets its **own copies**. Access to a capability/schema is only ever
through its owning pack — there is no shared catalog to reason about.

## Decision

### D1 — Ownership is a first-class field; the catalog is pack-scoped

Every `capabilities` and `artifact_schemas` document carries its **owning pack coordinates** — `pack_key` and
`pack_version` — and is created **for that pack version at onboarding**. Uniqueness becomes
`(pack_key, pack_version, capability_id, version)` for capabilities and
`(pack_key, pack_version, artifact_key, version)` for schemas. The same `capability_id`/`artifact_key` may now
exist under different pack versions as **independent rows** — that is the intended "own copy per pack." The
`created_by`/`created_at` provenance is retained.

> **Design call (flag for review):** ownership at **pack-version** granularity (each pack *version* owns its
> copies) rather than **pack_key** granularity (all versions of a pack share). Pack-version ownership makes a
> pack fully self-contained and makes deletion (ADR-061) a **pure cascade with zero reference-counting** — the
> cleanest fit for immutable packs. Cost: N versions of a pack hold N copies of each cap/schema (acceptable;
> immutability already implies per-version self-containment). If you prefer pack_key granularity, deletion of a
> single version gains an intra-pack "is any sibling version still referencing this?" check.

### D2 — Registration always creates the pack's own copies; no cross-pack reuse

Onboarding `commit` (and the seed loader) register each capability/schema **stamped with the committing pack's
`(pack_key, pack_version)`**, always as a fresh row — never reusing another pack's row. The Capabilities-step
**cross-pack clash check is removed** (a same-named id under a different pack is now legal and expected). The
id-namespacing-by-pack-slug convention may stay (harmless) but is no longer load-bearing for isolation —
ownership is.

### D3 — Reads are pack-scoped; the runtime bundle loader fetches a pack's own copies

The agent-runtime bundle loader currently fetches by global id: `GET /capabilities/{id}/{version}` /
`GET /artifact-schemas/{key}/{version}`. These become **pack-scoped**:
`GET /packs/{pack_key}/{pack_version}/capabilities/{capability_id}/{version}` and the analogous
`/artifact-schemas/...` (or the existing routes gain a required `pack_key`+`pack_version` scope). The
`RegistryClient.get_capability`/`get_artifact_schema` gain pack context (the loader already has it — it is
loading one specific pack). A pack can only ever load **its own** capabilities/schemas.

### D4 — Resolution/pinning stays within the pack

`activation.resolve_pins` (and `_pin_capability`/`_pin_artifact`) pin refs to versions **within the pack's own
owned rows**, not the global active catalog. A pack's resolution is computed only from what the pack owns.

### D5 — Re-namespace the seed reference packs to pack-owned copies

`wire-repair-agentic` and `wire-repair-standard` (and any other seed sharing `cap.payment.*`) are re-seeded so
each **owns its own** capability/schema copies stamped with its `(pack_key, pack_version)`. The shared
`cap.payment.*` rows are eliminated; each seed pack is self-contained like a copilot-onboarded pack. (Their
ids may be re-namespaced per pack or kept identical-but-owned — either satisfies the invariant since ownership,
not the id, provides isolation.)

### D6 — Migration: clean-slate

Dev, single-tenant, immutable seeds, routine `down -v`. **No in-place migration:** add the ownership fields +
new unique indexes, reset the stack (`docker compose … down -v`), and re-seed / re-onboard. After the sweep,
`capabilities`/`artifact_schemas` must contain **no row without `pack_key`+`pack_version`**, and no
cross-pack-shared row.

## Consequences

- Every capability/schema is owned by exactly one pack version; "what does this pack own?" is a single indexed
  query (`{pack_key, pack_version}`). This is the precondition ADR-061 needs to delete a pack as a clean
  cascade with no whole-catalog reference-counting.
- Packs are fully isolated: two packs onboarding the same MCP server hold independent copies; neither can
  perturb the other. No id-collision class, no silent reuse.
- Storage grows (per-pack, per-version copies) — deliberate and cheap; the correct trade for immutability +
  clean lifecycle.
- Breaking change to the catalog wire/read contract (pack-scoped routes) and the seed layout — taken at
  clean-slate; external readers of the old global catalog routes must move to the pack-scoped ones.
- The onboarding UI's "browse the global catalog" notion narrows: the Capabilities step already introspects MCP
  fresh per onboarding (ADR-049/057), so a global catalog browse is no longer meaningful; any such view becomes
  "this pack's owned capabilities."

## Scope boundaries (do not change)

Reference-domain **data** stays domain-named (wire/dine payloads, MCP servers, schema-version ids). The trigger
schema mechanism (ADR-049) is unchanged. HITL gating, the ADR-035 error-boundary path, and the ADR-059 trigger
vocabulary are untouched.

## Design calls fixed here (change in review, not in code)

1. **Pack-version** ownership granularity (per D1) — the cleaner fit; makes ADR-061 a pure cascade.
2. Reads are **pack-scoped routes** (per D3), not a `pack_key` query-param bolt-on — so "load another pack's
   capability" is structurally impossible, not merely discouraged.
3. **Clean-slate**, no migration (per D6).
