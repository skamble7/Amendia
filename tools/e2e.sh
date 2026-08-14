#!/usr/bin/env bash
# tools/e2e.sh — run the full-system Playwright e2e (primary e2e) against a running, minimally-seeded compose stack.
# The suite is self-contained: it onboards the ACH domain deterministically, runs the browser journeys, tears down.
#
#   docker compose -f backend/deploy/docker-compose.yml up -d          # empty, minimally-seeded stack (NO packs)
#   docker compose -f pega_stub/deploy/docker-compose.yml up -d        # for the ACH HITL journey
#   bash tools/e2e.sh                     # all journeys (onboard → run → teardown)
#   bash tools/e2e.sh --keep              # KEEP the onboarded stack (skip teardown) — reuse it in the UI / next run
#   bash tools/e2e.sh -g "owner"          # pass-through Playwright args (-g grep, --project, …)
#
# Playwright serves the webui itself (vite dev in ../webui, proxying /api/* to the compose backend via VITE_*_URL)
# and logs each persona in once. Endpoints default to the compose host ports; override via INGESTOR/RUNTIME/REGISTRY/
# GLEA/PEGA_STUB/STUB/KEYCLOAK/REALM/E2E_BASE_URL (see e2e/support/env.ts). Deps: `@playwright/test` +
# `npx playwright install chromium` (installed under e2e/). Exit non-zero on any failure (skips do not fail — a down
# stack / un-onboarded pack skips cleanly).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/e2e"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }

# --keep → skip teardown (leave the onboarded stack in place). Consumed here; not passed to Playwright.
PW_ARGS=()
for a in "$@"; do
  if [ "$a" = "--keep" ]; then export E2E_KEEP=1; else PW_ARGS+=("$a"); fi
done

if [ ! -d node_modules/@playwright/test ]; then
  echo "Missing @playwright/test. Install with:  (cd e2e && npm install && npx playwright install chromium)" >&2
  exit 2
fi

[ "${E2E_KEEP:-}" = "1" ] && bold "▶ Playwright e2e — KEEP mode (E2E_KEEP=1): the onboarded stack will be left in place"
bold "▶ Playwright e2e — npx playwright test"
LOG="$(mktemp)"
npx playwright test --reporter=list "${PW_ARGS[@]+"${PW_ARGS[@]}"}" 2>&1 | tee "$LOG"
CODE="${PIPESTATUS[0]}"

echo
bold "── per-journey summary ────────────────────────────"
grep -E "✓|✘|✗|-|›" "$LOG" | grep -E "tests/.*\.spec\.ts" \
  | sed -E 's/.*tests\/([a-z-]+)\.spec\.ts.*/  \1/' | sort | uniq -c \
  || echo "  (no journeys ran)"
grep -E "passed|failed|skipped" "$LOG" | tail -1
rm -f "$LOG"

echo
if [ "$CODE" -eq 0 ]; then bold "✅ e2e: no failures (green, or cleanly skipped)."; else bold "❌ e2e: failures above (exit $CODE)."; fi
exit "$CODE"
