# Claude Code prompt — Playwright e2e: **configurable teardown** + **relocate to a top-level `e2e/` folder**

Two follow-ups on the now-green Playwright suite. Both are structural/ergonomic — **do not change any test logic,
assertions, selectors, or the setup/onboarding behavior**. No git writes.

## 1. Make teardown configurable (keep the onboarded stack)

Today `global-teardown.ts` always removes the run's data (packs, `ach_exposure_cohort` definition, granted roles,
fired cases/cohorts). Add an **opt-out** so a run can leave everything in place — so the operator can use the UI
afterward without re-onboarding.

- Read an env flag via the existing `support/env.ts` helper — `E2E_KEEP` (truthy = **skip teardown entirely**).
  When set, `global-teardown` logs "keeping onboarded stack (E2E_KEEP set) — packs/cohort/roles/data left in place"
  and returns without deleting anything.
- Add a **`--keep`** convenience to `tools/e2e.sh` that sets `E2E_KEEP=1` for that run (still pass through other
  Playwright args). Document both.
- Semantics to preserve: setup is already **create-if-absent**, so a kept stack is simply **reused** on the next
  run (no double-onboard, no error). With `--keep`, granted roles + the published wizard pack + fired cases persist
  by design; note in the docs that data then accumulates until a normal (non-keep) run or a `down -v`.
- Default (flag unset) = today's behavior: full teardown, stack left as found.

## 2. Relocate the suite to a dedicated top-level `e2e/` folder

This is a **full-system** e2e (frontend + backend + stubs + DB), not a webui unit concern — move it out of
`webui/` into a top-level `e2e/`. **Pure relocation**: same tests, same behavior, only paths/wiring change.

- **Move** `webui/playwright.config.ts` → `e2e/playwright.config.ts`, and `webui/e2e/**`
  (`tests/`, `support/`, `pages/`, `fixtures/`, `global-setup.ts`, `global-teardown.ts`, `README.md`,
  and the `.auth/`/`.artifacts/` output dirs) → `e2e/**`. Fix the now-internal relative paths (they're
  self-contained, so this is mechanical).
- **Own `e2e/package.json`** with `@playwright/test` (the version currently in `webui`, `^1.62.1`) and the
  `e2e` / `e2e:report` scripts; its own `node_modules`. **Remove** `@playwright/test` and the `e2e`/`e2e:report`
  scripts from `webui/package.json` (the webui no longer owns the e2e).
- **`webServer`** in `e2e/playwright.config.ts` serves the webui from its new location — `command: "npm run dev"`
  with `cwd: "../webui"` (or `npm --prefix ../webui run dev`), keep `reuseExistingServer` and the `VITE_*` proxy
  env exactly as today. The webui build/serve is the only cross-boundary tie; nothing imports webui `src`.
- **`tools/e2e.sh`** — `cd` into `e2e/` (not `webui/`); update the missing-deps hint to
  `(cd e2e && npm install && npx playwright install chromium)`; keep the per-journey summary + `--keep` (item 1).
- **`.gitignore`** — ignore `e2e/node_modules`, `e2e/.artifacts`, `e2e/.auth`, `e2e/.report` (move any existing
  `webui/e2e/*` ignore lines).
- **Docs** — move `webui/e2e/README.md` → `e2e/README.md`; update `backend/docs/engineering/running-e2e-tests.md`
  for the new paths (`cd e2e …`, `bash tools/e2e.sh`, `bash tools/e2e.sh --keep`).
- **Confirm decoupling:** `webui` `tsc`/`vitest`/`build` and the webui `tsconfig` no longer reference `e2e/` (they
  already excluded it; verify nothing breaks after the move).

## Do not
- Do not change any test/spec logic, assertions, selectors, page objects, the onboarding journey, or the
  deterministic setup/onboarding + role-grant behavior — this is relocation + one env flag only.
- Do not reintroduce a `webui/src` dependency; do not move the co-located **vitest** component tests (those
  correctly stay next to the webui source).
- No git writes — leave the tree dirty.

## Acceptance
- From an empty, minimally-seeded stack (`down -v` → `up` → mcp_stub): `bash tools/e2e.sh` (run from repo root,
  now driving `e2e/`) is **green from empty** and green **back-to-back**, exactly as before the move — same journey
  count, no skips for missing data.
- `bash tools/e2e.sh --keep` (or `E2E_KEEP=1 …`) finishes green **and leaves the stack onboarded** — the ACH packs
  and `ach_exposure_cohort` definition are still present afterward (verifiable via `GET /packs` / the Cohorts
  Definitions tab / the UI), so no manual re-onboard is needed. A subsequent normal `tools/e2e.sh` reuses them and
  then tears down cleanly.
- `e2e/` is self-contained (own `package.json`, `npm install` + `npx playwright install chromium` there);
  `webui/package.json` no longer carries `@playwright/test` or the e2e scripts; webui `tsc`/`vitest`/`build` stay
  green.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_playwright_relocate_and_keep_report.md` (uncommitted):
(1) outcome one-liner; (2) the `E2E_KEEP`/`--keep` flag (where checked, what it preserves, reuse-on-next-run);
(3) the move — new `e2e/` layout, own `package.json`, the `webServer → ../webui` wiring, what left
`webui/package.json`, `.gitignore`/doc updates; (4) verification — green-from-empty + back-to-back + a `--keep`
run proving the stack stays onboarded, and webui build/vitest still green; (5) any follow-ups. One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/` (moved), `webui/package.json` (trim), `tools/`,
`.gitignore`, docs only. Relocation must be behavior-preserving; the only new behavior is the opt-out teardown flag.
