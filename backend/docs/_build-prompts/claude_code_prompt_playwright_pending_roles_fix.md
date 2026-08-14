# Claude Code prompt — Playwright e2e fix: grant ACH gate roles via **pending-staging** (HITL green from a clean stack)

Targeted fix. On a genuinely clean stack (`down -v`), `bash tools/e2e.sh` fails **only** `hitl-arc` because the ACH
role grant is **skipped**:

```
grant: no identity user with email marcus@amendia.dev
grant: no uid for 'marcus' — skipping role grant (HITL gates may be un-actionable)
```
→ marcus never gets `role.ach_*` → the "Authorize all" gate button stays **disabled** → the arc can't close.

**Root cause:** `e2e/fixtures/onboarding/onboard_ach.py` `grant_test_roles()` resolves the persona uid via priya's
admin `GET /users` (correctly avoiding marcus's own `/me`, which would poison the 30s `amendia_auth` role cache —
the documented gotcha #5). But identity users are **JIT-provisioned on first login**, so on a clean stack marcus
isn't in `/users` yet → grant skipped. Earlier green runs only passed because marcus was already provisioned from
prior activity. Avoiding marcus's `/me` removed the very thing that used to provision him.

**Fix:** identity's **pending-users** staging (`POST /pending {email, roles}`) assigns roles by email that
**materialize onto the user at JIT-provision time**. Pre-stage marcus's ACH gate roles before his first login
(global-setup already runs `ensureAchDomain()` **before** the persona logins), so his first login provisions him
with the roles live — fixing the clean-stack case **and** preserving the no-cache-poison property (no marcus token
is minted). On a reused (`--keep`) stack where marcus already exists, staging conflicts → fall back to the existing
admin grant.

## Read first
- `e2e/fixtures/onboarding/onboard_ach.py` — `_gate_roles()`, `_persona_uid()`, `grant_test_roles()`,
  `revoke_test_roles()`, `teardown()`, the `_http(IDENTITY, …)` helper, `GRANT_PERSONA = "marcus"`.
- `backend/services/platform/identity/app/routers/pending.py` — `POST /pending` (`StagePendingRequest {email,
  roles}`; 201; **conflict when the email already belongs to a provisioned user**), `DELETE /pending/{email}` (204).
- `backend/services/platform/identity/app/routers/admin.py` — `GET /users`, `POST /users/{uid}/roles` (the
  existing admin-grant fallback path), `DELETE /users/{uid}/roles/{role}`.
- `e2e/global-setup.ts` — confirms `ensureAchDomain()` (→ `onboard_ach.py`) runs **before** `loginPersona(...)`, so
  a pending stage created in setup is materialized at marcus's first login.

## Deliverables

### 1. `grant_test_roles()` — stage first, admin-grant fallback (`onboard_ach.py`)
- **Primary:** `POST {IDENTITY}/pending` with `{"email": "marcus@amendia.dev", "roles": _gate_roles()}` (priya's
  admin token, as today). On **201**, log `stage: marcus pending += <roles>` and return — the roles materialize at
  marcus's first login. **Do not mint a marcus token / call marcus's `/me`** (preserve the no-cache-poison property).
- **Fallback (already provisioned):** if `POST /pending` returns the "email already belongs to a provisioned user"
  conflict, resolve the uid via the existing `_persona_uid()` (admin `GET /users`) and grant each `_gate_roles()`
  role via `POST /users/{uid}/roles` (idempotent — 409 = already held), exactly as today.
- Keep it a pure fix: no fixed sleeps, no new deps, no ordering change (setup-before-login already holds).

### 2. `teardown()` / `revoke_test_roles()` — remove the stage too
- `DELETE {IDENTITY}/pending/{email}` (ignore 404 — it was consumed at provision, or never created), **and** the
  existing revoke via `_persona_uid()` + `DELETE /users/{uid}/roles/{role}` for the provisioned case. Idempotent;
  leave identity as found. (Under `--keep`, teardown is skipped — unchanged.)

## Do not
- Do not mint marcus's token or call his `/me` before the roles land (that reintroduces the 30s cache poisoning).
- Do not change the onboarding/pack logic, the global-setup ordering, or any test/spec. No git writes.

## Acceptance
- From a **truly clean** stack (`docker compose … down -v` → `up` → mcp_stub; marcus never provisioned),
  `bash tools/e2e.sh` is **green including `hitl-arc`** — the setup log shows `stage: marcus pending += …` (201),
  marcus logs in provisioned-with-roles, the Authorize gate is **enabled**, and the cohort reaches closed/Released.
- A `--keep` run leaves the stack onboarded; a **subsequent** `tools/e2e.sh` (marcus now provisioned) still goes
  green via the **admin-grant fallback** (pending conflict → `POST /users/{uid}/roles`), then tears down cleanly
  (roles revoked + pending stage deleted).
- No fixed sleeps; existing pytest smoke + webui `tsc`/`vitest`/`build` untouched.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_playwright_pending_roles_fix_report.md` (uncommitted):
(1) outcome one-liner; (2) the stage-first/admin-fallback logic + why pending-staging fixes the clean-stack case
without cache poisoning; (3) the teardown addition; (4) verification — a green `hitl-arc` from `down -v`
(clean stack) **and** a `--keep`→rerun proving the fallback; (5) whether the `running-e2e-tests.md` gotcha notes
need a one-line update (pending-stage now the primary path). One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `onboard_ach.py` (+ maybe a doc line) only; reuse the
existing `_http`/`_persona_uid`/`_gate_roles` helpers and priya's admin token. Deterministic, no marcus `/me` before
grant, idempotent teardown. Smallest change that makes `hitl-arc` green from a clean `down -v`.
