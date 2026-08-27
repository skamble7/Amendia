# `.gitignore` hygiene for the new test suites — audit + top-up

**Outcome:** every generated/temp output of the smoke (`backend/tests/smoke/`) and Playwright (`e2e/`) suites is
ignored; all committed inputs (lockfiles, fixtures, specs, configs) stay committable. Audit found **zero tracked
strays**. Only `.gitignore` changed (edit + dedupe); no git writes, tree left dirty.

## 1. Audit (report only)
`git ls-files` filtered for test outputs (`.artifacts`, `.auth`, `.report`, `blob-report`, `test-results`,
`node_modules`, `__pycache__`, `.pytest_cache`, `playwright-report`, `*.webm`, `*.zip`, `.DS_Store`, `*.log`,
`.last-run.json`) → **none tracked**. Nothing for the operator to `git rm --cached`. ✓

## 2. What was already covered vs. what I added
**Already present (not re-added):** `__pycache__/`, `.pytest_cache/`, `node_modules/`, `htmlcov/`, `.coverage`,
`.coverage.*`, `coverage.xml`, bare `.venv` (also matches `backend/tests/smoke/.venv/`), `*.log`, and the existing
Playwright block (`e2e/node_modules/`, `e2e/.artifacts/`, `e2e/.auth/`, `e2e/.report/`, `e2e/test-results/`).

**Added** (appended to the one Playwright/test-artifacts block, with an explanatory header):
```
e2e/blob-report/
e2e/playwright/.cache/
# Belt-and-suspenders for any Playwright run not scoped under e2e/:
playwright-report/
test-results/
```
`backend/tests/smoke/.venv/` was **not** added — the pre-existing bare `.venv` rule already matches it (verified).
Coverage/`htmlcov`/`__pycache__`/`.pytest_cache` were **not** re-added — already present.

**Dedupe:** the suite-relocation task had appended a second `# Editor backups` + `# OS generated files` block that
fully duplicated the original `# macOS`/`# Windows`/`# Linux` block. Collapsed it: removed the duplicate
`.DS_Store`, `.DS_Store?`, `._*`, `.Spotlight-V100`, `.Trashes`, `ehthumbs.db`, `Thumbs.db`, `*~`, `*.swp`; kept the
one unique line `*.swo` by adding it to the original block (next to `*.swp`). `.DS_Store` now appears **once**.

## 3. Tracked strays
**None.** (Expected, and confirmed.)

## 4. `git check-ignore` verification
**Ignored (rule matched):** `e2e/.artifacts/x.png` → `e2e/.artifacts/`; `e2e/.auth/priya.json` → `e2e/.auth/`;
`e2e/node_modules/x` → `e2e/node_modules/`; `backend/tests/smoke/__pycache__/x.pyc` → `__pycache__/`; `.DS_Store` →
`.DS_Store`; `e2e/blob-report/report.html` → `e2e/blob-report/`; `e2e/playwright/.cache/x` → `e2e/playwright/.cache/`;
`playwright-report/index.html` → `playwright-report/`; `test-results/x` and `e2e/test-results/.last-run.json` →
`test-results/`; `backend/tests/smoke/.venv/bin/python` → `.venv`. ✓

**NOT ignored (stay committable — no output):** `e2e/package-lock.json`, `webui/package-lock.json`,
`e2e/fixtures/camunda-gateways.bpmn`, `backend/tests/smoke/scenarios/ach_exposure.yaml`, `e2e/playwright.config.ts`,
`e2e/package.json`, `e2e/README.md`, `tools/e2e.sh`, `tools/smoke.sh`, `e2e/support/env.ts`, `e2e/pages/screens.ts`,
`e2e/tests/hitl-arc.spec.ts`, `backend/tests/smoke/test_smoke.py`. ✓

## 5. Fresh-run `git status`
The generated dirs from prior runs (`e2e/.artifacts`, `e2e/.auth`, `e2e/.report`, `e2e/node_modules`) exist on disk
but **do not appear** in `git status --porcelain` (filtered for those paths → empty) — i.e. a run produces no
untracked artifact entries. `git status --porcelain .gitignore` shows only ` M .gitignore`. ✓

## Note (out of scope, pre-existing)
`*.log` appears twice — under `# Django stuff:` (Python template) and `# Logs` (Node template), from concatenated
upstream `.gitignore` templates. Pre-existing, unrelated to the test suites, and in two distinct sections; left
as-is (only the `.DS_Store` dedupe was in scope). `.vscode/` and `.idea/` are already ignored per team convention —
unchanged.
