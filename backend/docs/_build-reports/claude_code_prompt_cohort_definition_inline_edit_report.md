# Functional inline edit for a cohort definition (backend PUT + detail-page editor): report

## 1. Outcome

"Edit definition" is real: a new owner-gated `PUT /cohort/definitions/{cohort_def_id}` updates a definition's
mutable fields, and the definition detail page edits them **in place** (no navigation to the blank create form).
`cohort_def_id` stays immutable; gating is unchanged (`role.process.owner`, enforced in UI **and** backend).

## 2. Backend (`process-registry`)

- **Model** (`models/cohort.py`): `CohortDefinitionUpdate(BaseModel)` — the mutable fields only (`display_name?`,
  `description?`, `close_schema`, `close_correlation_path`, `close_outcome_path?`). **No `cohort_def_id`** (it's
  the path param; immutable). A stray `cohort_def_id` in the body is ignored (default extra-ignore) — path wins.
- **Repo** (`cohort_def_repo.py`): `async def update(cohort_def_id, patch) -> Optional[CohortDefinition]` —
  `find_one_and_update({cohort_def_id}, {$set: patch + updated_at}, return_after)`. Only the patch fields +
  `updated_at` are `$set`, so **`created_at` is preserved** (never in the set), `updated_at` is bumped to
  `utcnow()`, `cohort_def_id` is untouched, and no unspecified stored field is dropped. Returns `None` if absent.
- **Route** (`cohort.py`): `@router.put("/definitions/{cohort_def_id}", response_model=CohortDefinition,
  dependencies=[_OWNER])`. The exact close-schema checks (`Draft202012Validator.check_schema` → 422 on malformed,
  `close_correlation_path` required) are factored into a shared `_validate_close(...)` now used by **both** POST
  and PUT — POST behaviour is byte-identical. `404` if the definition doesn't exist; returns the updated
  definition (200). Owner gate is the same `_OWNER = Depends(require_roles("role.process.owner"))` as create/delete.

## 3. Frontend (`webui`)

- **Service** (`api/services/cohorts.ts`): `updateCohortDefinition(cohortDefId, body)` → `PUT
  /cohort/definitions/{id}` (registry, `silent`), body = the 5 mutable fields (`CohortDefinitionUpdate` type).
- **Inline editor** (`CohortDefinitionPage.tsx`, owner-only via the existing `isOwner` gate): the `Edit
  definition` button now toggles an `editing` state (no `navigate`). In edit mode the **Definition card** renders
  editable controls — `display_name` (input), `description` (textarea), `close_correlation_path` (input),
  `close_outcome_path` (input), `close_schema` (monospace textarea seeded with the pretty-printed current schema)
  — and the header shows **Save** + **Cancel** instead of Edit; `cohort_def_id` + the Active badge stay read-only.
  **Validation before submit** (mirrors NewCohortPage): `close_schema` must `JSON.parse` and
  `close_correlation_path` must be non-empty → inline error blocks Save. On success: `updateCohortDefinition` →
  invalidate `["cohort-definitions"]` → success toast → exit edit. On `ApiError`: toast `detailText`, stay in edit.
  **Cancel** discards local state with no request. When ≥1 instance exists, a subtle non-blocking hint under the
  schema editor notes that schema/correlation changes affect **future** close recognition only (consistent with
  the forward-only membership warning). Delete, the Members editor, and the Instances panel are unchanged.

## 4. Verification

- **Registry** `uv run --extra dev pytest` → **383 passed** (+5 PUT cases in `test_cohort_phase2.py`): update
  returns the new fields; **`created_at` preserved + `updated_at` advanced**; body `cohort_def_id` ignored (path
  wins, and the "hacked" id 404s); **404** unknown id; **422** malformed `close_schema`; **403** non-owner (strict
  auth, mirrors `test_auth`). OpenAPI snapshot re-dumped (`scripts/dump_openapi.py`) → the `put` on
  `/cohort/definitions/{cohort_def_id}` is present; `test_openapi_snapshot` green.
- **webui** `npx tsc --noEmit` clean; `npx vitest run` → **28 files / 191 tests passed** (+3 inline-edit cases:
  owner edit+Save PUTs the new body and the card refreshes; invalid JSON blocks Save with an inline error; Cancel
  restores; a non-owner sees no Edit control). `npx eslint` on the touched files → 0 problems. `gen/registry.ts`
  regenerated from the snapshot (carries the new PUT).

## 5. Activation note (for the reviewer)

The new endpoint is only live after the **process-registry image is rebuilt**:
`docker compose build process-registry` (then restart it). A UI **Save** against the *old* image will
**404/405** — rebuild first.

## 6. Follow-ups

- The detail page still resolves the definition by scanning `useCohortDefinitions()`; a per-id
  `GET /cohort/definitions/{id}` exists and could back the page directly (cheap now, deferred).
- If definitions should be uneditable-while-instances-exist, that would be a server-side guard on PUT — not added
  (forward-only + the inline hint is the intended V1, consistent with membership edits).
- `gen:api:check` still needs the full stack up (only registry has an offline snapshot) — unchanged.
