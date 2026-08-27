# Playwright e2e — grant ACH gate roles via pending-staging (HITL green from a clean stack)

**Outcome:** on a genuinely clean stack (`down -v`), `hitl-arc` now passes — the setup **pre-stages** marcus's ACH
gate roles by email, so his first login provisions him already holding them, the "Authorize all" gate is enabled,
and the cohort closes **Released**. The only change is `e2e/fixtures/onboarding/onboard_ach.py` (+ two doc lines). No
git writes.

## 1. The fix — stage-first, admin-grant fallback (`grant_test_roles`)

- **Primary (clean stack):** `POST /pending-role-assignments {email: "marcus@amendia.dev", roles: _gate_roles()}`
  (priya's `role.platform.admin` token). Identity materialises staged roles onto the user at JIT-provision, and
  `global-setup` runs `ensureAchDomain()` **before** the persona logins — so marcus's first login provisions him with
  the roles live. On **201** we log `stage: marcus pending += […]` and **return without minting marcus's token or
  calling his `/me`**, preserving the no-cache-poison property (gotcha #5: `amendia_auth` caches roles by `(iss,sub)`
  for 30s). `stage_pending` **appends** (idempotent per role), so the ACH roles merge onto marcus's seed pending row
  (base `payments.*` roles) rather than replacing it.
- **Fallback (already provisioned, e.g. a reused `--keep` stack):** staging returns **409 `user_exists`**; we resolve
  the uid via the existing `_persona_uid()` (admin `GET /users`) and grant each role via `POST /users/{uid}/roles`
  (idempotent — 409 = already held). Any non-201/409 also falls through to this path.

**Why it fixes the clean case:** the prior code resolved the uid via admin `GET /users` (correct — avoids marcus's
`/me`), but identity users are **JIT-provisioned on first login**, so on a clean stack marcus isn't in `/users` yet →
grant was skipped → the gate button stayed disabled. Pending-staging assigns by **email before the user exists**, and
still never touches marcus's token — fixing the clean case without reintroducing cache poisoning.

## 2. Teardown (`revoke_test_roles`)

Now also `DELETE /pending-role-assignments/{email}` (404 is fine — the stage was consumed at provision, or never
created on the fallback path), **then** the existing `_persona_uid()` + `DELETE /users/{uid}/roles/{role}` for the
provisioned user. Idempotent; leaves identity as the seed intended (marcus provisioned with his base roles). Skipped
under `--keep`, unchanged.

## 3. Verification (all against the live stack)

| Scenario | Grant path | hitl-arc | Teardown |
|---|---|---|---|
| **Clean `down -v`** (marcus unprovisioned) | `stage: marcus pending += […]` **201** | **✓ closed/Released (14.3s)** | pending `404` (consumed) + roles revoked `200` + packs removed |
| **`--keep`** (marcus now provisioned) | fallback `POST /users/{uid}/roles` **201** | ✓ | skipped (stack kept: 3 ACH packs + marcus's roles retained) |
| **Final normal** (reused stack) | fallback **409 already held** (idempotent) | ✓ | pending `404` + roles revoked `200` + packs removed |

Clean-stack precondition confirmed before the run: only priya provisioned, **marcus absent from `/users`**, marcus's
seed pending row present (`payments.ops_approver`, `wire_repair.ops_approver`). No fixed sleeps added. My change is
confined to the e2e fixture, so **pytest smoke + webui `tsc`/`vitest`/`build` are untouched by construction.**

## 4. One separate finding (out of scope — pre-existing cold-stack fragility)

On the truly clean run, **`dag-sla-editor:48` also failed** — not hitl-arc. Its "forward-only warning" assertion needs
the `ach_exposure_cohort` definition to have **≥1 cohort instance** (`CohortDefinitionPage.tsx` renders the banner
only when `instances.length > 0`). It runs *before* `hitl-arc` fires the first case, so on a wiped stack there are no
instances → no banner. It passes on any warm stack (verified: green on the `--keep` and final runs, once an instance
existed). The prompt's premise "fails only hitl-arc" held because prior non-clean stacks retained instances across
teardowns (no cohort-instance delete API). **This is unrelated to the role grant and the prompt forbade test
changes, so I did not touch it.** Recommended follow-up: have that test `test.skip` when the definition has no
instances (mirroring its existing `!present` skip), or run it after a warmup case.

## 5. Doc updates

`backend/docs/engineering/running-e2e-tests.md`: gotcha #4/#5 note now describes **pending-stage as the primary grant
path** (admin-grant as the 409 fallback), and a "known cold-stack gap" line documents the `dag-sla-editor` instance
dependency above. No other docs needed.
