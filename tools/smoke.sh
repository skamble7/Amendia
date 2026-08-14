#!/usr/bin/env bash
# tools/smoke.sh — run the corpus full-stack smoke suite against a running, onboarded compose stack.
#
#   docker compose -f backend/deploy/docker-compose.yml up -d          # + onboard the three domains
#   docker compose -f pega_stub/deploy/docker-compose.yml up -d        # for ACH
#   bash tools/smoke.sh                # all domains
#   bash tools/smoke.sh -k ach         # one domain (pass-through pytest args)
#
# Endpoints default to the compose host ports; override via INGESTOR/RUNTIME/REGISTRY/GLEA/PEGA_STUB/STUB/
# KEYCLOAK/REALM/… (see backend/tests/smoke/config.py). Deps: pytest + httpx + pyyaml (all free/OSS):
#   pip install -r backend/tests/smoke/requirements.txt
#
# Exit non-zero if any domain fails (skips do not fail the run — a down stack / un-onboarded pack skips).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! "$PY" -c "import pytest, httpx, yaml" 2>/dev/null; then
  echo "Missing deps. Install with:  $PY -m pip install -r backend/tests/smoke/requirements.txt" >&2
  exit 2
fi

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
bold "▶ corpus smoke — pytest -m smoke backend/tests/smoke"

LOG="$(mktemp)"
# -p no:cacheprovider keeps it stateless; -o addopts= ignores any repo-wide pytest addopts.
"$PY" -m pytest -m smoke -v -ra -o addopts= -p no:cacheprovider backend/tests/smoke "$@" 2>&1 | tee "$LOG"
CODE="${PIPESTATUS[0]}"

echo
bold "── per-domain summary ─────────────────────────────"
# Each parametrized case is  test_corpus_smoke[<domain>]  → PASSED / FAILED / SKIPPED.
grep -oE "test_corpus_smoke\[[a-z_]+\] (PASSED|FAILED|SKIPPED|ERROR)" "$LOG" \
  | sed -E 's/test_corpus_smoke\[([a-z_]+)\] (.*)/  \1: \2/' | sort -u \
  || echo "  (no domains ran — is the stack up?)"
rm -f "$LOG"

echo
if [ "$CODE" -eq 0 ]; then
  bold "✅ smoke: no failures (green, or cleanly skipped)."
else
  bold "❌ smoke: failures above (exit $CODE)."
fi
exit "$CODE"
