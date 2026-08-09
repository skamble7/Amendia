# Claude Code prompt — functional **inline edit** for a cohort definition (backend PUT + detail-page editor)

Make "Edit definition" real. Today the button on `CohortDefinitionPage` just navigates to the blank
`/cohorts/new` create form, and there is **no backend update endpoint** — the registry only has
create / get / list / delete. Add a proper owner-gated `PUT` and an **inline edit mode** on the definition
detail page (per Sandeep's choice; delete already works). Backend first, then frontend.

Editable fields: `display_name`, `description`, `close_schema`, `close_correlation_path`, `close_outcome_path`.
**`cohort_def_id` is immutable** (instances + pack `cohort_membership` key on it) and is never editable.

Gating is **unchanged — process-owner only** (`role.process.owner`), enforced in the UI *and* the backend, same
as create/delete. (Non-owner personas like the Reviewer/Approver demo user simply won't see the edit controls;
that's intended.)

## Why

- The definition detail is the maintenance home for a cohort (ADR-063). Membership editing already lives there;
  the core fields (name, close contract, correlation/outcome paths) should be editable in place too.
- Routing Edit to `/cohorts/new` can't load or update an existing definition — it's a dead control.

## Read first

- `backend/services/process-registry/app/routers/cohort.py` — the definition router. `register_definition`
  (POST, `dependencies=[_OWNER]`) shows the exact close-schema validation to mirror (`Draft202012Validator.
  check_schema`, `close_correlation_path` required) and the `_OWNER = Depends(require_roles("role.process.owner"))`
  gate. `delete_definition` and `get_definition` show the 404 pattern.
- `backend/services/process-registry/app/models/cohort.py` — `CohortDefinitionBase` /
  `CohortDefinitionCreate` / `CohortDefinition` (`created_at`/`updated_at`, `to_doc`). Add the update body here.
- `backend/services/process-registry/app/dal/cohort_def_repo.py` — `insert` / `get` / `delete`. Add `update`.
- `webui/src/features/cohorts/CohortDefinitionPage.tsx` — the detail page. The read-only **Definition** card
  and the owner-gated header buttons (line ~110: `Edit definition` -> `navigate("/cohorts/new")` — the one to
  rewire). Note the existing `isOwner` gating and the forward-only membership warning pattern.
- `webui/src/features/cohorts/NewCohortPage.tsx` — the close-schema JSON parse/validate pattern
  (`JSON.parse` in a try/catch -> inline error) to reuse for the inline editor; extract a tiny shared helper if
  it's clean (e.g. into `membership.tsx`), otherwise mirror it.
- `webui/src/api/services/cohorts.ts` + `queries.ts` — where `createCohortDefinition` / `deleteCohortDefinition`
  live; add `updateCohortDefinition` beside them. The page already invalidates `["cohort-definitions"]`.

## Deliverables

### Phase A — backend: `PUT /cohort/definitions/{cohort_def_id}` (owner-gated)
1. **Model** (`models/cohort.py`): add `CohortDefinitionUpdate(BaseModel)` with the mutable fields only —
   `display_name?`, `description?`, `close_schema: Dict[str,Any]`, `close_correlation_path: str`,
   `close_outcome_path?`. **No `cohort_def_id`** (it's the path param; immutable).
2. **Repo** (`cohort_def_repo.py`): add `async def update(cohort_def_id, patch) -> Optional[CohortDefinition]`
   — 404-safe (returns `None` if absent), **preserves `created_at`**, **bumps `updated_at` to `utcnow()`**,
   leaves `cohort_def_id` unchanged. Use a targeted `$set` / `find_one_and_update(return_after)` or fetch-merge-
   replace — whichever matches the repo's style; do not drop unspecified stored fields.
3. **Route** (`cohort.py`): `@router.put("/definitions/{cohort_def_id}", response_model=CohortDefinition,
   dependencies=[_OWNER])`. Validate the close schema well-formed and `close_correlation_path` non-empty
   (**reuse the exact checks from `register_definition`** — factor a small helper if you like, but don't change
   POST's behaviour). `404` if the definition doesn't exist. Return the updated `CohortDefinition` (200).
4. **Tests** (mirror the existing cohort router/repo tests): update succeeds and returns the new fields;
   `created_at` preserved + `updated_at` advanced; `404` on unknown id; `422` on a malformed `close_schema`;
   **non-owner -> 403** (gate holds); `cohort_def_id` cannot be changed (path wins / body has no id).

### Phase B — frontend: inline edit mode on the definition detail page
5. **Service**: `updateCohortDefinition(cohortDefId, body): Promise<CohortDefinition>` -> `PUT
   /cohort/definitions/${cohortDefId}` (registry, `silent: true`), body = the 5 mutable fields.
6. **`CohortDefinitionPage` inline editor** (owner-only, reusing the existing `isOwner` gate):
   - Replace the `Edit definition` button's `navigate("/cohorts/new")` with an **`editing` toggle**. In edit
     mode the **Definition card** renders editable controls: `display_name` (input), `description` (textarea),
     `close_correlation_path` (input), `close_outcome_path` (input, optional), and `close_schema` (monospace
     textarea seeded with the pretty-printed current schema). The header shows **Save** + **Cancel** instead of
     Edit; `cohort_def_id` and the Active badge stay read-only.
   - **Validate before submit:** `close_schema` must parse as JSON and `close_correlation_path` must be
     non-empty — show an inline error and block Save otherwise (reuse the NewCohortPage parse pattern). On
     success: call `updateCohortDefinition`, invalidate `["cohort-definitions"]`, toast success, exit edit mode.
     On `ApiError`, toast `err.detailText` and stay in edit mode. **Cancel** restores the original values with no
     request.
   - When the definition has >=1 instance, show a subtle inline hint under the schema editor that close-schema /
     correlation-path changes affect **future** close-message recognition only (consistent with the existing
     forward-only membership warning; non-blocking).
   - Leave **Delete**, the **Members** editor, and the **Instances** panel exactly as they are.
7. **Test** (extend `cohorts.test.tsx`): as an owner, enter edit mode, change `display_name` + `close_schema`,
   Save -> asserts the `PUT` fired with the new body and the card reflects the update (list invalidated); invalid
   JSON blocks Save with an inline error; Cancel restores. A non-owner sees no Edit control (unchanged).

## Do not

- Do not make `cohort_def_id` editable, and do not add update to any other cohort surface — inline, on the
  definition detail, only.
- Do not change the gating — stays `role.process.owner` on both the new PUT and the UI controls. Do not touch
  create/delete/membership behaviour.
- Do not alter the instances list, rollups, `MemberDiagram`, or the instance-detail backlink.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- `PUT /cohort/definitions/ach_exposure_cohort` as an owner updates `display_name` + `close_schema` and returns
  the updated definition (`updated_at` advanced, `created_at` unchanged); as a non-owner -> **403**; unknown id ->
  **404**; malformed `close_schema` -> **422**.
- On the detail page (as a process-owner): **Edit definition** flips the Definition card into an editable form
  in place (no navigation); Save persists and the card + Definitions-tab reflect the change without a manual
  reload; Cancel restores; invalid JSON is blocked with an inline error.
- `pytest` (registry) green incl. the new PUT cases; `tsc`/`npm run build` clean; `vitest` green incl. the new
  inline-edit cases.
- **Note for the reviewer:** the new endpoint is only live after the `process-registry` image is rebuilt
  (`docker compose build process-registry`) — call this out; a UI Save will 404/405 against the old image.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_cohort_definition_inline_edit_report.md` (uncommitted):
(1) outcome one-liner; (2) backend changes (model `CohortDefinitionUpdate`, repo `update`, PUT route + shared
validation), how `created_at`/`updated_at` are handled, and the owner-gate; (3) frontend changes (service,
inline editor, validation reuse); (4) verification — exact `pytest` / `vitest` / build commands + results,
incl. the 403/404/422 cases; (5) the rebuild-`process-registry`-to-activate note; (6) any follow-ups. One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Backend before frontend. Reuse the existing
close-schema validation and the `isOwner` gate; smallest change that makes inline edit real without weakening
the owner-only contract.
