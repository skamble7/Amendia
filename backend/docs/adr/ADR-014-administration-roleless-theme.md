# ADR-014 — Administration UI (users, roles & staged access), the roleless-user state, and a real theme system

- **Status:** Accepted (auth §6 step 3 — administration surface)
- **Date:** 2026-07-08
- **Related:** **ADR-012** (auth backend — the identity service + `role.*` enforcement this extends);
  **ADR-013** (auth frontend — the `IdentityContext` / `RequireAuth` sequencing / role-gated nav / theme
  *scaffolding* this builds on, and whose deferred "identity/role admin screens" and roleless handling this
  delivers); `amendia_services_reference.md` (§5 endpoint contract — updated here); `webui/webui_user_guide.md`
  (→ v0.3); `backend/deploy/keycloak/README.md`.
- **Advances:** the **admin screens** deferred by ADR-013 ("assignment + enable/disable stay identity-API
  only"), the roleless-user experience (previously an empty dashboard with 403 noise), and turning the
  light-mode token scaffolding ADR-013 left dormant into a working provider + toggle.

## Context

ADR-012 gave the identity service list/get users, assign/revoke roles, disable/enable, and a
`pending_role_assignments` collection (roles staged by email, JIT-attached at first login) — but **no admin
API over the pending collection** and **no server-side guardrails** protecting an admin from locking
themselves out or emptying the platform of admins. ADR-013 built the SPA's `/me`-driven identity, role-gated
nav (Registry ⟷ `role.process.owner`), and account-disabled state, but explicitly deferred the **admin UI**
and left two rough edges:

- **A roleless user had no destination.** A user who signed in with zero roles resolved fine at `/me`, fell
  through `RequireAuth`, and landed on the app shell + dashboard — which then fired reads that showed nothing
  useful (and, before reads were made role-free, 403 noise). There was no calm "you have no access yet" state.
- **Light mode was scaffolding only.** Light tokens existed as a `:root.light` override in `index.css`, but
  nothing activated them: `index.html` hard-coded `class="dark"`, there was no `ThemeProvider`/toggle, and
  `tailwind.config.ts` declared `darkMode: "class"` while the tokens keyed off `:root` (dark) vs `:root.light`
  — so the `.dark` class was a dead label and only the sonner toaster consumed a (system) theme.

The governing principle is unchanged from ADR-012/013: **authenticate with the IdP, authorize in Amendia**;
the SPA reads roles from `/me`, progressive disclosure is UX-only, and the server enforces every request.

> **Design import.** This work was specified against a Claude Design prototype (`Amendia.dc.html`). The design
> MCP import could not run in the build environment (it needs an interactive `/design-login`), so the new
> screens were built from the written spec while **reusing the existing component library** (StatusChip,
> Badge, Table, Tabs, Dialog-over-Radix, EmptyState) rather than introducing parallel primitives.

## Decision

### Part A — identity service: pending-access admin API + guardrails

- **Pending-role-assignment CRUD** (`app/routers/pending.py`), all `require_roles("role.platform.admin")`:
  `GET /pending-role-assignments` (aggregated per email, optional case-insensitive `email` filter),
  `POST` (`{email, roles[]}` → 201; **422** if any role fails the `role.*` pattern; **409 `user_exists`**
  when the email already belongs to a provisioned user — the body carries that user's `amendia_user_id` so the
  UI redirects to their detail instead of staging a no-op), `PUT /{email}` (replace the staged set),
  `DELETE /{email}` (204; 404 if none). The collection now records **`staged_by`/`staged_at`**; **JIT attach
  behaviour is unchanged** (`ResolveService._materialise_pending_roles`). Rows stay one-per-`(email, role)`,
  preserving the existing unique index and the seed.
- **Guardrails** (`app/services/guardrails.py`), server-side and authoritative — the UI mirrors them as
  disabled controls but the server is the source of truth:
  - **`self_protection` (409):** an admin cannot disable their own account nor revoke their own
    `role.platform.admin` (checked before any mutation, independent of admin count).
  - **`last_admin` (409):** the platform must retain ≥1 *active* holder of `role.platform.admin`.
    Implemented **race-tolerantly**: the mutation is applied tentatively (`pop_assignment` / `set_status`),
    active admins are re-counted *after* it, and if the count hit zero the change is **rolled back**
    (restore the popped grant / re-enable the account) and refused. Two admins concurrently revoking each
    other therefore both restore, and at least one admin always survives.
- **`role_details` enrichment:** the admin user views (`GET /users`, `GET /users/{id}`, and the mutating admin
  responses) now include `role_details: [{role, assigned_by, assigned_at}]` for the detail screen's audit
  line; **`/me` deliberately omits it** (identity payload stays lean).
- **Dev realm + seed:** the committed realm export gains **alex** (seeded `role.platform.admin` *only* — proves
  the admin-only nav composition) and **sam** (no staged roles — first login exercises the roleless state).
  Seeding stays **by email → JIT-attach**; no provisioned users are fabricated in Mongo (users are born only by
  first sign-in). **+9 identity tests** (pending CRUD incl. the 409-existing-user shape, both guardrails incl.
  the last-admin restore, role-pattern validation); the existing suite stays green (23 total).

### Part B — webui: Administration screens + the roleless state

- **Administration → Users** nav entry, visible only with `role.platform.admin` (the same `requiresRole`
  mechanism as Registry). Routes `/admin/users` and `/admin/users/:userId` are wrapped in a client-side
  **`RequireRole`** gate (a deep-link without the role gets a calm forbidden state; the backend still enforces).
- **Users list (A1)** with **Users** and **Pending access** tabs: name/email, status chip (disabled rows
  muted), role badges (platform admin set apart), identity-issuer hint, first-seen; search + status/role/**no-roles**
  filters. Pending tab lists staged access (email, roles, staged-by/at, "activates on first sign-in") with
  stage/edit/remove. **User detail (A2)**: header with copyable `usr-…`; Roles block (per-role description +
  assigned-by/at + revoke, an Assign button, and a roleless inline-assign empty state); read-only Identities
  block (re-linking noted API-only); Account block (disable/enable). **Assign-role (A3)** and **Stage-access
  (A4)** dialogs (the latter offers a redirect on the `user_exists` 409). Mutations go through TanStack Query
  with broad invalidation; **optimistic UI is intentionally omitted** — correctness over flash for entitlement
  changes. The server's 409 codes (`self_protection` / `last_admin` / `user_exists`) are always handled as the
  source of truth even when the client pre-disabled a control.
- **Roleless-user state (A5):** `RequireAuth` gains a branch — a resolved identity with **zero roles** renders
  a calm full-page "no access yet" state (sign-out available), **replacing** the previous behaviour of dropping
  the user onto the app shell/dashboard.
- **Generated types** for the new endpoints/schemas were **hand-extended** in `api/gen/identity.ts` (the
  `gen:api` script needs the live compose stack; re-running it reproduces them 1:1) alongside a new
  `role_details` field on `UserView`.

### Part C — theme system (light / dark / system)

- **`ThemeProvider` + `useTheme`** (`app/theme.tsx`): modes `light | dark | system`, persisted to
  `localStorage`, `system` following `prefers-color-scheme` live via a media-query listener, applying exactly
  one of `.dark` / `.light` to `<html>`.
- **Class reconciliation** (the one convention, aligned everywhere): dark stays the `:root` default and is also
  emitted under `.dark`, light is `.light`, and `tailwind.config.ts`'s `darkMode: "class"` is now **live**
  (the previously-dead `.dark` label drives the `dark:` variant correctly in both themes). A **pre-paint inline
  script** in `index.html` applies the persisted/system class before first paint (no flash); the hard-coded
  `class="dark"` is removed. The sonner toaster now follows the provider instead of `"system"`.
- **Toggle** in the top-bar user menu (Light / Dark / System) — one of the permitted touches to an existing
  surface.
- **Light-mode sweep:** the codebase was already token-disciplined — the only hard-coded color found was the
  BPMN canvas `bg-white`, replaced with a named **`--canvas`** token (deliberately light in both themes, since
  bpmn-js renders fixed dark strokes). No layouts were restyled.

### Part D — docs & tests

Services reference §5/§6 (new endpoints, guardrail codes, alex/sam), user guide → **v0.3** (Administration
section, troubleshooting, changelog, users table), and the persona map (full **Alex — Platform Administrator**
profile + coverage matrix; "role administration is API-only" struck from Priya's friction). **webui: 40 tests
green** (admin list/detail, guardrail-disabled controls, pending CRUD + existing-user redirect, roleless
routing, theme provider); `lint` / `test` / `build` green.

### Deliberate deviation — operator nav gating

The definition of done requires a platform-admin-**only** user (alex) to see *only* Administration in his nav.
The operator nav entries (dashboard / inbox / instances / exceptions) were **ungated**, so an admin-only user
would have seen them all. They are now gated to the operator role set (`OPERATOR_ROLES` = analyst / approver /
process-owner). This is a third touch beyond the two the drift guardrail nominally permits, chosen because it
leaves **every existing persona's nav byte-identical** (riya/marcus/priya all remain operators) and changes
visibility **only** for the new admin-only persona — which is the entire reason alex exists. Reads stay
role-free server-side, so this is nav-level progressive disclosure, not enforcement; the `/` landing redirect
is likewise role-aware (`HomeRedirect`) so an admin-only user lands in Administration rather than an off-nav
dashboard. It is isolated to `AppShell.tsx` + `HomeRedirect.tsx` and trivially revertible.

## Consequences

- **Identity/role administration is now a UI, not just an API.** A platform admin lists and searches users,
  assigns/revokes roles, disables/enables accounts, and stages access by email — with the platform-integrity
  guardrails enforced server-side and surfaced as disabled controls. The identity service is IdP-agnostic as
  before; nothing here reads a vendor claim.
- **Roleless users have a home.** Zero-role sign-in lands on a calm "ask your administrator" page instead of an
  empty dashboard, closing the gap ADR-013 left. The full lifecycle is now demonstrable end-to-end: sam signs
  in → roleless state → alex assigns `ops_analyst` → sam re-signs-in → the analyst app.
- **Light mode works and survives reload.** One theme convention drives Tailwind, the tokens, the pre-paint
  script, and sonner; `system` follows the OS live. The token system already carried the whole surface, so the
  sweep touched exactly one feature file (`BpmnViewer.tsx`, one class).
- **Deliberately deferred:** SCIM / automated provisioning (staging by email is the bridge), identity
  re-linking/merging UI (still API-only), audit-log browsing (audit remains `assigned_by/at` + `staged_by/at`,
  no history store — the disable "reason" is a client-side friction gate, not persisted), self-service access
  requests, IdP-config UI, session policies, and the SSE/notification push (live surfaces still poll).
- **Traps recorded for maintainers:**
  1. **`gen:api` is stack-dependent.** The identity `gen/identity.ts` pending endpoints + `role_details` were
     hand-written because the generator needs the live services up; re-run `pnpm gen:api` against the running
     identity service to regenerate (it reproduces them). Keep the hand-edits in lockstep with the router until
     then.
  2. **Guardrail counts are of *active* admins and re-checked post-mutation.** The last-admin check counts
     users holding `role.platform.admin` whose status is `active`, *after* the tentative change, and rolls back
     on zero. A disabled admin does not count; don't "optimise" this into a pre-check — the rollback is what
     makes it race-tolerant.
  3. **Theme scheme is dark-`:root`-default + `.dark`/`.light` classes.** `darkMode: "class"` now depends on the
     `ThemeProvider` (or the pre-paint script) always stamping exactly one class on `<html>`. If you change the
     storage key, change it in both `app/theme.tsx` and the inline script in `index.html`.
  4. **Admin nav gating is invisible to existing personas by design.** `OPERATOR_ROLES` gates the operator nav
     so an admin-only user sees only Administration; every operator persona is unaffected. Removing the gate
     re-shows the (read-only-accessible) ops screens to admins — a product choice, not a security one.

## Addendum — 2026-07-09 (loose ends closed)

Two follow-ups from the implementation session were resolved against the running stack:

- **Generated API types are now 100% generator-owned (Trap #1 retired).** With compose up, `pnpm gen:api`
  regenerated `webui/src/api/gen/identity.ts` from the live identity `/openapi.json`; the output is
  shape-identical to the hand-extended version (webui `tsc` / tests / build stayed green with **no**
  call-site changes) and now carries the backend docstrings. The other four services regenerated with a
  banner-only change — no undocumented API drift. `gen/` is no longer hand-edited. Two guards were added:
  an env-independent `// GENERATED — DO NOT HAND-EDIT` banner emitted by `scripts/gen-api.mjs`, and
  **`pnpm gen:api:check`** (`scripts/gen-api-check.mjs`) — regenerates into a temp dir and exits nonzero on
  any drift (CI-ready; pipeline wiring is out of scope). The guardrail error bodies
  (`self_protection` / `last_admin` / `user_exists`) stay FastAPI `detail` dicts (unmodeled in OpenAPI), so
  their TS shape lives with its consumer in `features/admin/queries.ts` (documented there) rather than in
  `gen/`. Live admin flows — list, `role_details`, assign/revoke, stage + the **409 `user_exists`** response,
  and disable/revoke **self_protection** — were spot-verified via a real `priya` bearer.
- **Persona map located + corrected.** There is no standalone `amendia_persona_map.md`; the content this ADR
  called the "persona map" lives in `webui/webui_user_guide.md` §10, where Alex was already a full profile +
  coverage matrix. That was verified and tightened (explicit implemented actions; `Sam` noted as the
  roleless-state demonstrator; a "genuinely future personas" note = SCIM lifecycle + audit reporting; role
  wording aligned to the in-app `ROLE_DESCRIPTION`). The one stale reference — "future UI screen for the
  tenant-admin persona" in `amendia_auth_architecture.md` — now points at the shipped Administration UI, and
  user-guide ↔ admin-guide cross-links were added. *Known, left untouched (admin-guide edits are the owner's):
  `amendia_admin_user_management_guide.md`'s back-link to the user guide resolves inside `backend/docs/` and
  is broken.*
