#!/usr/bin/env bash
# tools/e2e.sh — the reliable CI GATE: the full-system Playwright e2e against a running, minimally-seeded compose
# stack. Self-contained: it onboards the ACH domain DETERMINISTICALLY (rule-based infer_draft, no LLM), runs the
# browser journeys, and tears down. Fast, reproducible, LLM-free — this is what gates. No flags.
#
# The copilot/LLM lifecycle journey is a SEPARATE, non-blocking command — see `tools/e2e-copilot.sh` (its own
# config, real model, retains everything, skips when the model is absent). It is EXCLUDED here.
#
#   docker compose -f backend/deploy/docker-compose.yml up -d          # empty, minimally-seeded stack (NO packs)
#   docker compose -f pega_stub/deploy/docker-compose.yml up -d        # for the ACH HITL journey
#   bash tools/e2e.sh                     # all deterministic journeys (onboard → run → teardown)
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

if [ ! -d node_modules/@playwright/test ]; then
  echo "Missing @playwright/test. Install with:  (cd e2e && npm install && npx playwright install chromium)" >&2
  exit 2
fi

bold "▶ Playwright e2e (deterministic gate) — npx playwright test"
LOG="$(mktemp)"
# The copilot lifecycle spec is excluded by the config's testIgnore; this runs the deterministic journeys only.
npx playwright test --reporter=list "$@" 2>&1 | tee "$LOG"
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
