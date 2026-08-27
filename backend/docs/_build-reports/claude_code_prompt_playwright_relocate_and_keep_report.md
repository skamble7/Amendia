# Playwright e2e — configurable teardown (`--keep`) + relocation to a top-level `e2e/`

**Outcome:** the suite now lives in a self-contained top-level `e2e/` package and runs **green from empty, green
back-to-back, and green with `--keep` (leaving the stack onboarded)** — identical journeys/behavior to before the
move. webui `tsc` / `build` / `vitest` (204 tests) stay green. Zero test/assertion/selector/setup changes. No git
writes; tree left dirty.

```
Run A (from empty):                 13 passed, 1 skipped   → teardown removed packs
Run B (back-to-back normal):        13 passed, 1 skipped   → teardown removed packs
Run C (--keep):                     13 passed, 1 skipped   → teardown SKIPPED; 3 ACH packs + cohort def + marcus roles left in place
Run D (normal, reuses kept stack):  13 passed, 1 skipped   → setup "already active (skip)"; teardown removed packs (0 ACH packs after)
webui: tsc ✓  build ✓  vitest 29 files / 204 tests ✓
```
The 1 skip is the pre-existing closed-cohort SLA-board observation (runs before any closed cohort exists) — same as before.

## 1. Configurable teardown — `E2E_KEEP` / `--keep`

- **Flag:** `KEEP_STACK` in `e2e/support/env.ts` — `E2E_KEEP` truthy (`1|true|yes|on`).
- **Checked in** `e2e/global-teardown.ts`: when set, it logs
  `keeping onboarded stack (E2E_KEEP set) — packs/cohort/roles/data left in place` and returns **without deleting
  anything** (packs, `ach_exposure_cohort` definition, granted `role.ach_*` roles, fired cohorts all persist).
- **Convenience:** `tools/e2e.sh --keep` consumes the arg locally and exports `E2E_KEEP=1` (all other args still
  pass through to Playwright); prints a KEEP-mode banner.
- **Reuse semantics:** setup is create-if-absent, so a kept stack is **reused** next run (verified: Run D logged
  `already active (skip)` for all three packs + `already exists (skip)` for the definition, no double-onboard), then
  torn down normally. With `--keep`, data accumulates until a normal run or `down -v`. Default (unset) = today's full
  teardown.

## 2. Relocation — `webui/e2e/**` → top-level `e2e/`

Pure, behavior-preserving move (frontend + backend + stubs + DB is a full-system concern, not a webui unit one):

- **Moved** `webui/playwright.config.ts` → `e2e/playwright.config.ts` and all of `webui/e2e/**`
  (`tests/`, `support/`, `pages/`, `fixtures/`, `global-setup.ts`, `global-teardown.ts`, `README.md`) → `e2e/**`.
  Output dirs (`.auth/`, `.artifacts/`, `.report/`) regenerate under `e2e/`; `webui/e2e/` removed.
- **Config paths** are now config-relative: `testDir: ./tests`, `outputDir: ./.artifacts`,
  `globalSetup/Teardown: ./global-*.ts`, html `outputFolder: .report`.
- **Internal path fixes** (self-contained, mechanical): `env.ts` `SCENARIOS_DIR` `../../backend…` → `../backend…`;
  `onboard_ach.py` `parents[4]` → `parents[3]` (both now resolve to the repo root from the new depth).
- **`webServer → ../webui`:** the only cross-boundary tie. `command: "npm run dev -- --port 5173 --strictPort"`
  with `cwd: <abs>/webui` (computed from `import.meta.url`, since vite is CWD-sensitive); `reuseExistingServer` and
  the `VITE_*` proxy (webui/.env) unchanged. Nothing imports webui `src` (verified — no `@/` or `src` imports).
- **Own `e2e/package.json`** (`@playwright/test ^1.62.1`, `js-yaml`, `@types/*`; `e2e`/`e2e:report` scripts) with its
  own `node_modules`. **Removed** `@playwright/test` + the `e2e`/`e2e:report` scripts from `webui/package.json`.
- **`tools/e2e.sh`** now `cd`s into `e2e/`; install hint → `(cd e2e && npm install && npx playwright install
  chromium)`; per-journey summary grep retargeted `e2e/tests/…` → `tests/…` (Playwright now reports paths relative
  to the `e2e/` config). Fixed an empty-array `set -u` expansion (`"${PW_ARGS[@]+…}"`) so a no-arg run works on
  macOS bash.
- **`.gitignore`** — added `e2e/{node_modules,.artifacts,.auth,.report,test-results}/` (there were no `webui/e2e/*`
  ignore lines to move).
- **Docs** — `README.md` moved to `e2e/README.md` (links + commands updated, `--keep` documented);
  `backend/docs/engineering/running-e2e-tests.md` updated for the new `e2e/` paths, the top-level-suite framing, and
  a `--keep` section.
- **Decoupling confirmed** — webui `tsconfig` includes only `["src","scripts","vitest.setup.ts"]` (never referenced
  `e2e/`); `webui/package.json` carries no `playwright`; webui `tsc`/`build`/`vitest` green after the trim.

## 4. Verification
Green-from-empty (A), back-to-back (B), `--keep` leaving the stack onboarded (C, verified via `GET /packs` +
`/cohort/definitions/ach_exposure_cohort` + marcus's retained `role.ach_*`), and reuse-then-clean-teardown (D,
verified 0 ACH packs after). webui `tsc`/`build`/`vitest` all green.

## 5. Follow-ups
- None required. Optional: the per-journey summary still prints the `_smoke` line raw because the pre-existing
  `[a-z-]+` name pattern excludes the leading underscore — cosmetic, unchanged from before the move.
- The webui still lists `js-yaml`/`@types/js-yaml` in devDependencies (now only used by the moved suite); left in
  place to stay within the "trim `@playwright/test` + e2e scripts only" scope — safe to prune later if desired.
