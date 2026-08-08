# Claude Code prompt — ADR-061: clean deletion of a process pack (version or whole pack)

Implement **ADR-061** in the Amendia monorepo. Read
`backend/docs/adr/ADR-061-clean-deletion-of-a-process-pack.md` in full first — it is the contract; this is the
execution plan. This builds on ADR-060 (pack-owned caps/schemas), which is already implemented and verified.

## Goal in one line

Let a **process-owner** cleanly delete a **pack version** or an **entire pack** — a cascade that removes every
row for that pack across all collections (including its ADR-060-owned capabilities/schemas and committed
onboarding sessions) — **force-delete at any status**, **audited to GLEA before** the rows are removed.

## Decisions already made (ADR-061 — do not re-open)

- **Process-owner only** (`require_roles("role.process.owner")`), no other role.
- **Force-delete any status** (draft/validated/active/deprecated), **no** deprecate-first gate and **no** runtime
  liveness check. Safeguards: owner-role + destructive UI confirm + durable GLEA audit. Deleting an active pack
  (or one with paused instances) can strand in-flight instances on resume — record status-at-delete in the audit
  `detail`; that risk is the operator's to own.
- **Audit-first ordering:** emit the `delete` lifecycle event(s) BEFORE removing rows, so the GLEA trail survives
  a partial failure. Whole-pack delete emits **one `delete` event per version**.
- Cascade is a **pure ownership query** (ADR-060) — no reference-counting; nothing is shared.
- Committed `onboarding_sessions` for the deleted pack are **purged**.

## Read first

- `backend/services/process-registry/app/routers/packs.py` — `_OWNER = Depends(require_roles("role.process.owner"))`,
  `_require_pack`, and the existing lifecycle endpoints (activate/deprecate) whose shape the DELETE endpoints
  mirror; how `emit_pack_lifecycle(...)` is called (op/actor/detail) and how the authenticated user id is obtained
  for `actor`.
- `app/routers/onboarding.py` (`@router.delete("/{session_id}")`) — the existing DELETE pattern to follow.
- `app/dal/pack_repo.py` — `get`, `list_versions`, `get_resolution`, `save_pack_roles`/`get_pack_roles`,
  `save_validation_report`; the injected sidecar collections (`_validation`, `_resolutions`, `_pack_roles`). Add
  delete methods here.
- `app/dal/bpmn_repo.py` — add a delete for `bpmn_documents`.
- `app/dal/capability_repo.py` / `app/dal/artifact_schema_repo.py` — `list_owned(pack_key, pack_version)` exists
  (ADR-060); add `delete_owned(pack_key, pack_version)`.
- `app/dal/onboarding_repo.py` — `delete_one(session_id)` exists; the session model (`models/onboarding.py`) has
  `pack_key`+`version`. Add a delete-by-pack(+version).
- `app/db/mongo.py` — the collection constants: `PROCESS_PACKS`, `BPMN_DOCUMENTS`, `VALIDATION_REPORTS`,
  `PACK_RESOLUTIONS`, `PACK_ROLES`, `CAPABILITIES`, `ARTIFACT_SCHEMAS`, `ONBOARDING_SESSIONS`.
- `app/events/publisher.py` — `emit_pack_lifecycle(publisher, *, pack_key, version, op, actor, detail)`
  (fail-soft) and `libs/amendia_contracts/amendia_contracts/governance_events.py` — `PackLifecycleOp` (extend).
- `app/services/activation.py` (resolver reads active packs from Mongo per-request — confirm there's no
  in-memory pack cache to invalidate on delete; note it if there is).
- Webui: `webui/src/features/registry/PackDetailPage.tsx` (add the delete action + the pack-scoped caps/schemas
  views already there), `queries.ts`, `webui/src/api/gen/registry.ts` (regenerate), and how the UI reads the
  current user's roles (to gate the button).

## Phase 1 — Contract

1. Extend `PackLifecycleOp` with `DELETE = "delete"`. (`PackLifecycleEvent` already carries pack_key/version/op/
   actor/detail — no other contract change.)

## Phase 2 — DAL delete methods (idempotent `delete_many`, scoped by pack coords)

2. `pack_repo`: `delete_version(pack_key, version)` and `delete_pack(pack_key)` that remove the `process_packs`
   row(s) **and** the per-version sidecars they own — `bpmn_documents`, `validation_reports`, `pack_resolutions`,
   `pack_roles` (via the injected collections). Each `delete_many` scoped by `{pack_key(, version)}`, a no-op if
   already gone.
3. `capability_repo.delete_owned(pack_key, pack_version)` and `artifact_schema_repo.delete_owned(pack_key,
   pack_version)` — `delete_many({pack_key, pack_version})`.
4. `onboarding_repo.delete_for_pack(pack_key, version=None)` — delete sessions whose committed `pack_key`
   (and `version` when given) match.

## Phase 3 — Delete service + endpoints

5. A `deletion` service that, for a version or a whole pack, executes the ADR-061 **audit-first, ordered,
   idempotent** cascade:
   1. Resolve target version(s) (`list_versions` for whole-pack). If none exist → 404.
   2. For each version, `emit_pack_lifecycle(op="delete", actor=<owner user id>, detail=<status-at-delete + a
      purge summary>)` — **before** deleting.
   3. Delete `process_packs` row(s) first (immediately un-loadable/un-resolvable), then the per-version sidecars,
      then the pack-owned `capabilities`/`artifact_schemas`, then the committed `onboarding_sessions`.
   4. Return a summary: versions removed, and counts of sidecars/caps/schemas/sessions purged.
6. Endpoints in `packs.py`, both `dependencies=[_OWNER]`:
   - `DELETE /packs/{pack_key}/{version}` → delete one version (200 with summary, 404 if absent).
   - `DELETE /packs/{pack_key}` → delete every version (200 with per-version summary, 404 if no such pack).
   Force-delete regardless of status; do **not** require deprecate-first.

## Phase 4 — Close the ADR-060 D3 read gap (nested collection routes)

7. Add pack-scoped **collection** reads so a pack's owned catalog is reachable structurally, not via a global
   query-param browse: `GET /packs/{pack_key}/{pack_version}/capabilities` and `.../artifact-schemas` (back by
   `list_owned`). Restrict or retire the global `GET /capabilities` / `GET /artifact-schemas` browse to the
   onboarding-reuse use only (or remove if now unused). This honors ADR-060 design-call #2 ("pack-scoped routes,
   not a query-param bolt-on").

## Phase 5 — Frontend

8. `PackDetailPage`: add a **Delete** action (owner-only — gate on the current user having `role.process.owner`;
   hide/disable otherwise). A destructive confirm dialog names `pack_key@version` (or "all N versions"), shows the
   status, and warns that force-deleting an active pack can strand in-flight instances. On confirm, call the
   DELETE endpoint, then navigate back to the pack list and invalidate the packs query. Offer both "delete this
   version" and "delete entire pack" where the UI lists versions.
9. Repoint the pack-scoped caps/schemas views (from the ADR-060 UI follow-up) to the new **nested collection
   routes** from Phase 4 (dropping the `?pack_key=&pack_version=` browse). Regenerate `registry.ts`; update
   `queries.ts` and tests.

## Do not

- Do not require deprecate-first or add a runtime liveness gate (force-delete is the decision).
- Do not soft-delete / tombstone — this is a physical purge (immutability is preserved: manifests are never
  mutated, only wholly removed + audited).
- Do not change ADR-059 vocabulary, HITL gating, the ADR-035/type-compat guards, or reference-domain data.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- As process-owner: `DELETE /packs/{key}/{version}` removes that version and its owned caps/schemas/sidecars/
  sessions; `DELETE /packs/{key}` removes all of them. A Mongo check shows **zero** rows for that pack in every
  collection afterwards. A non-owner gets 403; unknown pack → 404.
- A `PackLifecycleEvent` with `op=delete` is emitted per deleted version (verify it reaches glea-service /
  ClickHouse) **and** the emit happens before the row removal (audit-first).
- Re-running a delete on an already-deleted pack is a clean no-op (idempotent).
- The pack detail page shows an owner-only Delete action with a destructive confirm; after delete the pack is
  gone from the list. Caps/schemas views use the nested routes.
- Backend `pytest` green (`process-registry`, `agent-runtime`); webui `tsc` + tests green; OpenAPI client
  regenerated.
- Live: onboard a pack, delete a version, then delete the pack; confirm clean removal + the GLEA audit trail
  survives (query the pack's lifecycle events after the pack rows are gone).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR061_clean_pack_delete_report.md` (uncommitted):
(1) outcome one-liner; (2) the DAL delete methods + endpoints + the cascade order; (3) the audit-first wiring and
the new `DELETE` op; (4) the Phase-4 nested routes + what happened to the global browse; (5) the frontend delete
action + role-gating; (6) verification — commands + results (`pytest`, the owner-only/404/idempotency checks, the
GLEA-audit-survives check, a Mongo "zero rows remain" check, both e2e deletes); (7) anything left open. Keep it to
a screen or two.

## Working agreement

You do not run git write commands — leave the tree dirty for Sandeep to review and commit. Prefer the fix at the
right layer over a shim. Stay inside the Amendia repo and the scope above.
