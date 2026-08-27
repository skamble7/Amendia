# Claude Code prompt — `.gitignore` hygiene for the new test suites (audit + top-up, no stray artifacts)

We added a pytest smoke suite (`backend/tests/smoke/`) and a full Playwright suite (`e2e/`). Make sure their
**generated/temp outputs can never be committed**, without ignoring the things that *should* be tracked
(lockfiles, committed fixtures, specs). **This is largely already in place — audit first, add only the gaps, don't
duplicate.**

## Current state (verified — do not re-add these)
Root `.gitignore` already has: `__pycache__/`, `.pytest_cache/`, `node_modules/`, `.DS_Store` (**listed twice —
lines ~164 and ~247; dedupe to one**), and a **Playwright block**: `e2e/node_modules/`, `e2e/.artifacts/`,
`e2e/.auth/`, `e2e/.report/`, `e2e/test-results/`. No stray artifact/cache/auth file is currently tracked.

## Deliverables

### 1. Audit what's tracked (report only — no git writes)
- Run `git ls-files` and confirm **nothing** matching test output is tracked:
  `e2e/.artifacts`, `e2e/.auth`, `e2e/.report`, `e2e/node_modules`, `e2e/test-results`, `**/__pycache__`,
  `**/.pytest_cache`, `*.webm`, `*.zip` traces, `.DS_Store`, `*.log`, blob/playwright reports.
- If any ARE tracked, **do not `git rm --cached`** (operator owns git) — **list them in the report** so Sandeep
  un-tracks them. (Expected: none.)

### 2. Top-up the gaps in `.gitignore` (append to the existing test/e2e block; no duplicates)
- **Playwright leftovers** not yet covered: `e2e/blob-report/`, `e2e/playwright/.cache/`,
  `e2e/test-results/.last-run.json` (covered by `test-results/`, fine), and — belt-and-suspenders for any
  non-`e2e/`-scoped run — generic `playwright-report/` and `test-results/`.
- **Python/coverage** the smoke may emit: `.coverage`, `.coverage.*`, `htmlcov/`, `coverage.xml`,
  and a smoke virtualenv if one is ever made: `backend/tests/smoke/.venv/`.
- **OS/editor strays** (you're on macOS; keep minimal): ensure `.DS_Store` (deduped), `*~`, `*.swp`, `*.swo`.
  Leave `.vscode/` / `.idea/` to team convention — only add if the team already ignores them elsewhere.
- Keep entries **anchored/commented** under one clear "test artifacts" section; do not scatter or duplicate.

### 3. Explicitly DO NOT ignore (these must stay committable)
Verify none of the below are matched by any ignore rule (use `git check-ignore -v <path>` on a sample of each):
- Lockfiles: `e2e/package-lock.json` (and the webui lockfile) — committed for reproducible installs.
- Committed test inputs: `e2e/fixtures/**` (the Camunda BPMN, onboarding fixtures), `e2e/support/**`,
  `e2e/pages/**`, `e2e/tests/**`, `backend/tests/smoke/scenarios/*.yaml`, `backend/tests/smoke/*.py`.
- The suites' own config/docs: `e2e/playwright.config.ts`, `e2e/package.json`, `e2e/README.md`,
  `tools/e2e.sh`, `tools/smoke.sh`.
- (Leave the `backend/docs/_build-prompts/` and `_build-reports/` docs alone — not this task's concern.)

## Verify
- `git check-ignore -v e2e/.artifacts/x.png e2e/.auth/priya.json e2e/node_modules/x backend/tests/smoke/__pycache__/x.pyc .DS_Store`
  → **all match** an ignore rule.
- `git check-ignore e2e/package-lock.json e2e/fixtures/camunda-gateways.bpmn backend/tests/smoke/scenarios/ach_exposure.yaml e2e/playwright.config.ts`
  → **no output** (i.e. NOT ignored — they stay committable).
- `git status --porcelain` after a fresh `bash tools/e2e.sh` run shows **no** `.artifacts/`/`.auth/`/`.report/`/
  `test-results/` entries as untracked (they're ignored).
- `.gitignore` has **no duplicate** lines (the doubled `.DS_Store` collapsed).

## Do not
- No git write commands (no `add`/`commit`/`rm --cached`) — edit `.gitignore` only, and **report** any tracked
  strays for Sandeep to remove. Leave the tree dirty.
- Do not ignore lockfiles, committed fixtures/specs, configs, or the docs. Do not scatter duplicate rules.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_gitignore_test_hygiene_report.md` (uncommitted):
(1) outcome one-liner; (2) what was already covered vs. what you added (the exact new lines) + the `.DS_Store`
dedupe; (3) the audit result — any already-tracked strays (expected none) listed for the operator; (4) the
`git check-ignore` verification (artifacts ignored; lockfiles/fixtures/specs NOT ignored); (5) a fresh-run
`git status` proving no artifacts appear. Half a screen.

## Working agreement
No git write commands — `.gitignore` edit + audit/report only; leave the tree dirty for Sandeep. Additive and
de-duplicated; ignore generated outputs, never the committed inputs/lockfiles/config.
