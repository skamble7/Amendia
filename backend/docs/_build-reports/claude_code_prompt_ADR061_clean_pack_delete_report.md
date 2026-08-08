# ADR-061 — Clean deletion of a process pack: implementation report

## 1. Outcome

**Done.** A process-owner can force-delete a **pack version** (`DELETE /packs/{key}/{version}`) or an **entire
pack** (`DELETE /packs/{key}`) at any status — an audit-first, ordered, idempotent cascade that removes every
row for that pack across all collections (incl. its ADR-060-owned capabilities/schemas + committed onboarding
sessions), with a durable GLEA `delete` audit written **before** the rows. Backend `pytest` green
(process-registry **364**, agent-runtime **343/4skip**, glea **49**); webui `tsc` clean + **173** tests; OpenAPI
client regenerated. Verified live end-to-end incl. the GLEA trail surviving the row removal.

## 2. DAL methods + endpoints + cascade order

- **DAL (idempotent `delete_many`, scoped by pack coords):**
  `pack_repo.delete_version(pack_key, version)` / `delete_pack(pack_key)` — delete `process_packs` **first**,
  then the sidecars this repo owns (`validation_reports`, `pack_resolutions`, `pack_roles`); returns counts.
  `bpmn_repo.delete(pk,ver)`/`delete_pack(pk)`. `capability_repo.delete_owned(pk,pv)` /
  `artifact_schema_repo.delete_owned(pk,pv)` (pure ADR-060 cascade — no reference-counting).
  `onboarding_repo.delete_for_pack(pack_key, version=None)` (matched on `basics.pack_key`/`basics.version`).
- **Service** `app/services/deletion.py::delete_versions(...)` runs the D5 order per version:
  (1) emit `delete` audit event, (2) `process_packs` first (+ owned sidecars), (3) `bpmn_documents`,
  (4) `capabilities`/`artifact_schemas`, (5) `onboarding_sessions`. Whole-pack = the per-version cascade for
  every `list_versions(...)` row + a final pack_key-scoped sweep so **zero** rows remain; `resolver.invalidate()`
  when an active pack was removed (it caches active packs).
- **Endpoints** in `packs.py`, both `dependencies=[_OWNER]` (`role.process.owner`): `DELETE /packs/{pack_key}/
  {version}` (404 if absent) and `DELETE /packs/{pack_key}` (404 if no versions). Return the purge summary.

## 3. Audit-first wiring + the new op

- `PackLifecycleOp` gained **`DELETE = "delete"`** (`governance_events.py`). The cascade calls the existing
  fail-soft `emit_pack_lifecycle(op="delete", actor=<owner amendia_user_id>, detail=…)` **before** any
  `delete_many`, so the GLEA record (ClickHouse — a separate SOR) survives a partial row-removal failure. A
  whole-pack delete emits **one `delete` event per version**. `detail` records status-at-delete and, for an
  active pack, the strand-warning ("in-flight instances may strand if they resume against the removed bundle").
  Force-delete: no deprecate-first, no liveness gate (D4).

## 4. Phase-4 nested routes + the global browse

Added structural pack-scoped **collection** reads (ADR-060 D3): `GET /packs/{pack_key}/{pack_version}/
capabilities` and `.../artifact-schemas` (backed by `list_owned`). The global `GET /capabilities` / `GET
/artifact-schemas` browse were **kept** (the onboarding wizard's cross-pack reuse browse still uses
`GET /capabilities`); the webui pack-detail views were **repointed** off the query-param browse onto the nested
routes. The OpenAPI snapshot (`webui/openapi/registry.json`) was regenerated via `scripts/dump_openapi.py`.

## 5. Frontend delete action + role-gating

`PackDetailPage` reads `const { hasRole } = useIdentity(); canDelete = hasRole(ROLE.processOwner)` and hides the
delete UI entirely for non-owners. **Delete version** sits in the header actions (destructive button →
`window.confirm` naming `pack_key@version`, showing status, warning force-delete can strand in-flight instances →
`deletePackVersion` → toast + invalidate `["packs"]`/`["pack",…]`/`["pack-versions",…]` → navigate `/registry`).
**Delete entire pack (all N versions)** sits in the `VersionsTab`. `usePackCapabilities`/`usePackSchemas` now
fetch the nested collection routes. `registry.ts` regenerated; `queries.ts` + `registry.test.tsx` updated.

## 6. Verification

- `process-registry` pytest → **364 passed** (new `tests/test_deletion.py` — audit-first proof, purge-every-
  collection, idempotent cascade, version/whole-pack endpoints, unknown→404; + `test_auth.py::
  test_delete_wrong_role_403`). `agent-runtime` **343/4skip**, `glea-service` **49**.
- `webui` `tsc` clean; `npm test` **173 passed / 27 files**; registry OpenAPI client regenerated; snapshot test green.
- **Live** (rebuilt registry+glea; owner=`priya` `role.process.owner`, non-owner=`riya`):
  - `DELETE /packs/wire-repair-standard/1.0.0` — riya **403**, unknown pack **404**, priya **200** with purge
    summary (`process_packs=1, capabilities=10, artifact_schemas=9, bpmn_documents=1, pack_resolutions=1`).
  - Mongo after: **0** rows for the pack across every collection; re-delete → **404**.
  - **GLEA audit survives**: `glea.audit_events` has `kind=pack_lifecycle, op=delete, pack_key=wire-repair-
    standard, version=1.0.0, actor=usr-…(priya), detail="force-delete … at status=active; WARNING: …"` — present
    even though every Mongo row for the pack is gone (audit-first + separate SOR).
  - **Whole-pack**: re-onboard → `DELETE /packs/wire-repair-standard` → **200** (`whole_pack=true`), 0 rows
    remain, `GET /packs/wire-repair-standard` → **404**.

## 7. Left open

- **Endpoint-level re-delete returns 404** (per the ADR "404 if absent" contract). The *cascade* is idempotent
  (delete_many no-ops) — a retry after a PARTIAL failure where `process_packs` is already gone can't re-enter via
  the endpoint (it 404s on the missing manifest), so orphan cleanup after such a partial failure would be a
  manual/DAL call. Acceptable for a dev/governance tool (Mongo delete_many rarely partially fails within a call);
  flagged for review if a "sweep even if manifest absent" retry is wanted.
- The seed **CLI** `onboard_seed` was wired with its resolution sidecar in the ADR-060 follow-up; the rebuilt
  registry image now stores resolutions on seed onboard (used here for the whole-pack re-onboard).
- Deleting an **active** pack with paused instances can strand them on resume — by design (D4), owner-gated +
  confirmed + audited (recorded in the event `detail`).
