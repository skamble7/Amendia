# ADR-060 — Pack-owned capabilities & schemas: implementation report

## 1. Outcome

**Done.** Every `capabilities`/`artifact_schemas` row is now OWNED by exactly one pack VERSION (`pack_key`+`pack_version`), stamped at registration; all reads are pack-scoped; the agent-runtime loads a pack's bundle only from that pack's own copies via pack-scoped routes. Backend `pytest` green (process-registry **358**, agent-runtime **343 passed / 4 skipped**); webui `tsc` clean + **169** tests; OpenAPI client regenerated. Live clean-slate (`down -v` + re-seed) verified: **0 unowned, 0 cross-pack-shared** rows, and the runtime fetched every cap/schema via `/packs/.../…`. Full happy-path e2e to `End_Resolved` is blocked only by an **environmental** gap (the seed pack's LLM `draft_repair` needs AWS creds), not by ADR-060. This unblocks ADR-061 (clean pack deletion) — "what does this pack own?" is now a single `{pack_key, pack_version}` query.

## 2. Ownership fields, indexes, routes

- **Contracts** (`libs/amendia_contracts/…/capability.py`, `artifact_schema.py`): added required `pack_key: str` + `pack_version: SemVerStr` to `CapabilityDescriptor` and `ArtifactSchemaRegistration`.
- **Indexes** (`process-registry/app/db/mongo.py`): unique `(pack_key, pack_version, capability_id, version)` and `(pack_key, pack_version, artifact_key, version)`; added a `(pack_key, pack_version)` index (the ADR-061 ownership query); kept `status`/`kind`/`created_at`.
- **DAL** (`capability_repo.py`, `artifact_schema_repo.py`): rewritten pack-scoped — `get/list_by_id|key/set_status/previous_version` all take `(pack_key, pack_version)`; `insert` takes the owner from the model; added `list_owned(pack_key, pack_version)`. No global-by-id lookup remains.
- **Routes changed** (`routers/capabilities.py`, `artifact_schemas.py`, `main.py`): retired the global-by-id `GET /capabilities/{id}[/{version}]` + deprecate; added pack-scoped
  `GET /packs/{pack_key}/{pack_version}/capabilities/{capability_id}[/{version}]`, the analogous `/artifact-schemas/…`, and the pack-scoped deprecate. `POST /capabilities` + `/introspect-mcp`, `POST /artifact-schemas`, and the browse lists `GET /capabilities`/`GET /artifact-schemas` (now "all owned rows", with optional `pack_key`/`pack_version` filters) stayed.

## 3. Registration / onboarding — always own, never share

- `registration.validate_schema`: `$ref` resolution + backward-compat `previous_version` now scoped to `reg.pack_key`/`reg.pack_version` (a pack is self-contained).
- `onboarding.py`: `_compose`/`commit` STAMP the session's `(pack_key, version)` onto every `CapabilityDescriptor`/`ArtifactSchemaRegistration` before insert; `hydrate_from_pack` stamps the new version's own copies; the dry-run `_CapOverlay`/`_SchemaOverlay` and every internal `list_by_id`/`list_by_key`/`get` are pack-scoped. **The cross-pack id-clash check at the Capabilities step was removed** (a same-named id under a different pack is now legal — ownership, not the id, provides isolation).
- `activation.resolve_pins` + `_pin_capability`/`_pin_artifact`: pin refs only against the pack's OWN owned rows (`repo.list_by_id/list_by_key(pack_key, pack_version, …)`).
- `pack_validator.validate()`: stamps `self._pack_key/_pack_version` from the manifest; every schema/cap read is pack-scoped. `copilot/reconcile.py`: pack-scoped schema read.

## 4. Bundle-loader change (agent-runtime)

`clients/registry_client.py`: `get_capability(pack_key, pack_version, capability_id, version)` / `get_artifact_schema(pack_key, pack_version, artifact_key, version)` call the pack-scoped routes. `engine.py::_fetch_bundle` (which already knows the pack it's loading) passes those coords to every fetch — a pack can only ever load its OWN copies; cross-pack callees each load their own. `bundle.py::from_seed_dir` stamps the seed pack's coords.

## 5. Seed re-own (D5)

`seeding/onboard_seed.py`: reads `manifest.json` first, then injects `pack_key`+`pack_version` into each capability/schema dict before `model_validate`, and uses pack-scoped idempotency `get`s. The two wire-repair seeds no longer share `cap.payment.*`/`art.*` — each owns stamped copies. (Seed JSON files were NOT edited — ownership is stamped at load, exactly like a copilot onboard.) Also wired the seed CLI's `ProcessPackRepository` with its validation/resolution/roles sidecars so a re-seeded pack stores its resolution (the runtime refuses a pack whose resolution it can't load).

## 6. Verification (commands + results)

- `cd backend/services/process-registry && uv run --extra dev pytest` → **358 passed** (incl. new `tests/test_pack_ownership_isolation.py`).
- `cd backend/services/agent-runtime && uv run --extra dev pytest` → **343 passed, 4 skipped**.
- **Isolation** (`test_pack_ownership_isolation.py`): the same `cap.payment.screen_party@1.0.0` / `art.payment.wire_exception@1.0.0` registered under `pack-alpha` AND `pack-beta` — both inserts succeed; `list_owned`/`list_by_id`/`get` each return only the queried pack's row. Passes.
- **Clean-slate live** (`docker compose down -v` → up → seed `wire-repair-standard`): Mongo check → `capabilities: total=10 unowned=0 shared_across_packs=0`, `artifact_schemas: total=9 unowned=0 shared=0`, all stamped `wire-repair-standard@1.0.0` (the formerly-shared `cap.payment.*` now owned).
- **Pack-scoped bundle load (live)**: a wire `unable_to_apply` trigger → the runtime fetched EVERY capability + schema via `GET /packs/wire-repair-standard/1.0.0/capabilities/…` and `/artifact-schemas/…` (all 200) — proving D3. `resolve_pins` pinned all 10 caps from the pack's own owned rows.
- **webui**: `npx tsc --noEmit` → 0; `npm test` → 169 passed; `src/api/gen/registry.ts` regenerated from the canonical `openapi/registry.json` (pack-scoped getters threaded through the HITL artifact editor + instance views); registry OpenAPI snapshot test green.

## 7. Open for the reviewer

- **Design call (per ADR D1):** ownership is at **pack-version** granularity — confirm in review, not code (makes ADR-061 a pure cascade).
- **Full wire happy-path e2e to `End_Resolved`** was not reached **live** here: after clean-slate, the `wire-repair-standard` seed's `cap.payment.draft_repair` is an LLM capability that resolves `dev.llm.bedrock.explicit-creds` and then needs AWS creds via a secret provider not wired in dev (`FileSecretProvider only supports file:*; got env:AWS_ACCESS_KEY_ID`). Environmental, orthogonal to ADR-060 — the instance still reached a terminal outcome and the pack loaded pack-scoped. (config-forge LLM profiles were re-seeded to get past the earlier 404.)
- **Dine-in e2e** needs a copilot re-onboard (no dine-in *seed* exists — it's a copilot example) which requires the LLM; the double-onboard isolation is proven by the unit test instead.
- **agent-runtime legacy local capability/schema DAL + routers** remain global-by-id; the runtime reads packs over HTTP from the registry, not from that store, so it's unused on the load path — only the seed-load boundary was stamped to satisfy the now-required contract fields. A full pack-scoping of that unused legacy store was out of scope; flag if you want it retired.
- The seed CLI resolution-sidecar wiring (§5) is a small correctness fix for `python -m app.seeding.onboard_seed`; the container image predates it, so I stored the resolution via the app's `resolve_pins` for this run — a rebuild picks up the CLI fix.
