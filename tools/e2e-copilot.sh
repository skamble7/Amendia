#!/usr/bin/env bash
# tools/e2e-copilot.sh — the NON-BLOCKING copilot/LLM lifecycle command. Drives the REAL copilot autopilot through
# the UI to onboard the 3 ACH segments, forms the ach_exposure_cohort over them, runs the 3 pega flows, and RETAINS
# everything (packs, cohort, instances, roles) for inspection — NO teardown. It is SEPARATE from the deterministic
# gate (`tools/e2e.sh`), never gates CI, and SKIPS cleanly when the stack has no copilot model
# (502 copilot_llm_unavailable). Uses its own Playwright config (playwright.copilot.config.ts) — no deterministic
# ACH onboarding, no teardown.
#
# Needs: the copilot MODEL configured on the stack, the mcp_stub servers, and pega_stub. RE-RUN NEEDS A CLEAN DB —
# because it retains everything, a second run finds the cohort definition present and skips with a "wipe the DB"
# message (down -v → up, then re-run).
#
#   docker compose -f backend/deploy/docker-compose.yml up -d          # empty, minimally-seeded stack (NO packs)
#   docker compose -f pega_stub/deploy/docker-compose.yml up -d        # the ACH mock Pega orchestrator
#   bash tools/e2e-copilot.sh                # onboard (real LLM) → form cohort → 3 flows → RETAIN (no teardown)
#   bash tools/e2e-copilot.sh -g "Released"  # pass-through Playwright args
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/e2e"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }

if [ ! -d node_modules/@playwright/test ]; then
  echo "Missing @playwright/test. Install with:  (cd e2e && npm install && npx playwright install chromium)" >&2
  exit 2
fi

bold "▶ Playwright e2e — COPILOT lifecycle (real LLM, retains everything, non-blocking)"
LOG="$(mktemp)"
npx playwright test --config playwright.copilot.config.ts --reporter=list "$@" 2>&1 | tee "$LOG"
CODE="${PIPESTATUS[0]}"

echo
grep -E "passed|failed|skipped" "$LOG" | tail -1
rm -f "$LOG"

echo
if [ "$CODE" -eq 0 ]; then
  bold "✅ copilot e2e: green (or cleanly skipped — no model). Onboarded packs/cohort/instances RETAINED for inspection."
else
  bold "❌ copilot e2e: failures above (exit $CODE). Onboarded state (if any) retained for inspection."
fi
exit "$CODE"
