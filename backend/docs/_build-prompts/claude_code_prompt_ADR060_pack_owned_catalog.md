# Claude Code prompt — ADR-060: pack-owned capabilities & schemas (evict the shared catalog)

Implement **ADR-060** in the Amendia monorepo. Read
`backend/docs/adr/ADR-060-pack-owned-capabilities-and-schemas.md` in full first — it is the contract; this is
the execution plan. This is the **prerequisite** for ADR-061 (clean pack deletion); do not implement deletion
here.

## Goal in one line

Make every `capabilities` and `artifact_schemas` row **owned by exactly one pack version** (stamped with
`pack_key` + `pack_version`), sourced fresh from MCP introspection at onboarding — so two packs using the same
MCP server hold **independent copies** and there is no shared catalog. Reads (including the agent-runtime bundle
loader) become **pack-scoped**.

## Decisions already made (do not re-open)

- **Pack-version ownership granularity** — each pack *version* owns its copies (not pack_key-wide). Uniqueness:
  `(pack_key, pack_version, capability_id, version)` and `(pack_key, pack_version, artifact_key, version)`.
- **Reads are pack-scoped routes**, not a query-param bolt-on.
- **Seeds re-namespaced to pack-owned** copies (no shared `cap.payment.*`).
- **Clean-slate migration** — add fields + indexes, `down -v`, re-seed/re-onboard. No in-place migration.

## Read first

- `backend/services/process-registry/app/db/mongo.py` — collection constants + `create_indexes` (the unique
  indexes to change).
- `app/dal/capability_repo.py`, `app/dal/artifact_schema_repo.py` — `insert` / `get` / `list_by_id` /
  `list_by_key` / `set_status`; add `pack_key`+`pack_version` to the key everywhere.
- `libs/amendia_contracts/amendia_contracts/capability.py`, `artifact_schema.py` — the `CapabilityDescriptor` /
  `ArtifactSchemaRegistration` models (add the ownership fields).
- `app/services/registration.py` — `register_schema` (+ wherever capabilities are inserted at commit); stamp
  ownership.
- `app/services/onboarding.py` — `commit` / `_compose` / the Capabilities-step cross-pack **clash check**
  (lines ~260-263, 284) to remove; `hydrate_from_pack` (edit-session re-register).
- `app/services/activation.py` — `resolve_pins`, `_pin_capability`, `_pin_artifact` (pin within the pack's own
  owned rows).
- `app/routers/capabilities.py`, `app/routers/artifact_schemas.py` — the global-by-id read routes to make
  pack-scoped (or add pack-scoped routes and retire the global ones).
- `backend/services/agent-runtime/app/clients/registry_client.py` (`get_capability`/`get_artifact_schema`) and
  the **bundle loader** that calls them (`app/engine/bundle.py` / wherever `load_bundle` resolves caps/schemas)
  — thread pack context.
- `backend/services/agent-runtime/seed/**` and the process-registry seed loader (`app/seeding/onboard_seed.py`)
  — the seed packs sharing `cap.payment.*` to re-own.
- `webui/src/api/gen/registry.ts` + the onboarding/registry features — regenerate the client for the new routes;
  update any global-catalog browse to pack-scoped.

Run `rg -n "capabilities/|artifact-schemas/|capability_id|artifact_key" backend libs webui` to build the full
touch-list before starting.

## Phase 1 — Contracts + storage (registry)

1. Add `pack_key: str` and `pack_version: SemVerStr` to `CapabilityDescriptor` and `ArtifactSchemaRegistration`
   (required going forward; stamped at registration).
2. `db/mongo.py`: change the capability unique index to `(pack_key, pack_version, capability_id, version)` and
   the schema index to `(pack_key, pack_version, artifact_key, version)`; keep the `status`/`created_at`
   indexes; add an index on `(pack_key, pack_version)` (the ownership query ADR-061 will use).
3. `capability_repo.py` / `artifact_schema_repo.py`: every read/write is scoped by `(pack_key, pack_version)` —
   `insert` stamps them; `get`, `list_by_id`/`list_by_key`, `set_status` take pack coordinates. No global-by-id
   lookups remain.

## Phase 2 — Registration + onboarding (always own, never share)

4. `registration.register_schema` (and the capability registration at commit): stamp the committing pack's
   `(pack_key, pack_version)`; always insert a fresh owned row (never reuse another pack's).
5. `onboarding.py`: **remove** the cross-pack clash check at the Capabilities step (a same-named id under a
   different pack is now legal); `_compose`/`commit` register owned copies; `hydrate_from_pack` (edit → new
   version) registers the new version's own copies.
6. `activation.resolve_pins` + `_pin_*`: pin refs to versions **within the pack's own owned rows**, not a global
   active catalog.

## Phase 3 — Pack-scoped reads + the runtime bundle loader

7. Registry: expose pack-scoped reads —
   `GET /packs/{pack_key}/{pack_version}/capabilities/{capability_id}/{version}` and
   `GET /packs/{pack_key}/{pack_version}/artifact-schemas/{artifact_key}/{version}` (retire or hard-scope the
   old global-by-id routes). The list routes (`GET /capabilities`, `GET /artifact-schemas`) become
   pack-scoped or clearly "all owned rows" — pick per the ADR and note it.
8. agent-runtime `registry_client.get_capability`/`get_artifact_schema` take `pack_key`+`pack_version`; the
   bundle loader (which already knows the pack it is loading) passes them. A pack can only load **its own**
   caps/schemas.

## Phase 4 — Seeds + webui + clean-slate

9. Re-seed the reference packs (`wire-repair-agentic`, `wire-repair-standard`, and any sharing `cap.payment.*`)
   so each **owns** its capability/schema copies stamped with its `(pack_key, pack_version)` — no shared rows.
10. Regenerate `webui/src/api/gen/registry.ts` from the new OpenAPI; update the onboarding/registry UI so any
    "catalog" view is the pack's owned caps/schemas (the Capabilities step already introspects MCP fresh).
11. Bring the stack up from `down -v`, re-seed, and onboard both reference domains via the copilot.

## Do not

- Do not implement pack deletion (that is ADR-061).
- Do not change the ADR-059 trigger vocabulary, HITL gating, or the ADR-035 error-boundary / type-compat guard.
- Do not rename reference-domain payload data or schema-version ids.
- No git writes (no add/commit/push/branch) — leave the tree dirty; the operator owns commits.

## Acceptance

- Every `capabilities` / `artifact_schemas` row has `pack_key`+`pack_version`; **no** row without them, and no
  row shared across two packs (`rg`/a Mongo count both confirm post-seed).
- Onboarding the **same MCP server** into two different packs yields **two independent** capability/schema sets
  (demonstrate with a test or a scripted double-onboard).
- The agent-runtime loads a pack bundle **only** from that pack's owned caps/schemas (pack-scoped fetch); a wire
  `unable_to_apply` trigger and a dine-in trigger both run to their terminal outcome on the re-seeded packs.
- Backend `pytest` green for `process-registry` and `agent-runtime`; webui typecheck/tests green; OpenAPI client
  regenerated cleanly.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR060_pack_owned_catalog_report.md` (uncommitted):
(1) outcome one-liner; (2) the ownership fields + new indexes + which read routes changed; (3) how registration
/ onboarding now stamp ownership and where the clash check was removed; (4) the bundle-loader change; (5) the
seed re-own; (6) verification — exact commands + results (`pytest`, the double-onboard isolation check, both
e2e flows, a Mongo check that no unowned/shared rows remain); (7) anything left open for the reviewer. Keep it
to a screen or two.

## Working agreement

You do not run git write commands — leave the tree dirty for Sandeep to review and commit. Prefer the fix at the
right layer over a shim. Stay inside the Amendia repo and the scope above.
