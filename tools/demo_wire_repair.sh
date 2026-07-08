#!/usr/bin/env bash
# tools/demo_wire_repair.sh
#
# End-to-end acceptance narrative for the wire-repair-standard vertical slice:
#   generate → ingest → resolve → dispatch → accept → run (HITL gates via API) → completed.
#
# Assumes the compose stack is up:
#   docker compose -f backend/deploy/docker-compose.yml up --build
#
# Requires: curl, jq.  Override endpoints with STUB/INGESTOR/RUNTIME env vars.
set -euo pipefail

STUB="${STUB:-http://localhost:8081}"
INGESTOR="${INGESTOR:-http://localhost:8082}"
RUNTIME="${RUNTIME:-http://localhost:8083}"
REASON="${1:-AC01}"

command -v jq >/dev/null || { echo "jq is required"; exit 1; }

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

user_for_role() {
  case "$1" in
    role.payments.ops_analyst)  echo "analyst-1" ;;
    role.payments.ops_approver) echo "approver-1" ;;
    *) echo "user-x" ;;
  esac
}

decision_for_mode() {
  # manual gates are "completed"; every other mode is "approved".
  [ "$1" = "manual" ] && echo "complete" || echo "approve"
}

poll() { # poll <url> <jq-filter> <want> <label> [max]
  local url="$1" filt="$2" want="$3" label="$4" max="${5:-60}" i=0 got=""
  while [ "$i" -lt "$max" ]; do
    got="$(curl -sf "$url" 2>/dev/null | jq -r "$filt" 2>/dev/null || true)"
    [ "$got" = "$want" ] && { echo "$got"; return 0; }
    case "$want" in
      __terminal__) [ "$got" = "completed" ] || [ "$got" = "failed" ] && { echo "$got"; return 0; } ;;
    esac
    sleep 1; i=$((i+1))
  done
  echo "TIMEOUT waiting for $label (last='$got')" >&2
  return 1
}

step "1. Generate a wire exception (reason_code=$REASON) at the stub"
GEN="$(curl -sf -X POST "$STUB/exceptions/generate" \
        -H 'content-type: application/json' \
        -d "{\"reason_code\":\"$REASON\",\"count\":1}")"
EXC_ID="$(echo "$GEN" | jq -r '.created[0].exception.exception_id')"
RK="$(echo "$GEN" | jq -r '.created[0].routing_key')"
bold "  exception_id = $EXC_ID   (published on $RK)"

step "2. Wait for the ingestor to ingest → resolve → dispatch → accepted"
poll "$INGESTOR/ingestions/$EXC_ID" '.status' 'accepted' 'ingestion=accepted' 60 >/dev/null
ING="$(curl -sf "$INGESTOR/ingestions/$EXC_ID")"
PID="$(echo "$ING" | jq -r '.process_instance_id')"
echo "  ingestion status : $(echo "$ING" | jq -r '.status')"
echo "  resolved pack    : $(echo "$ING" | jq -r '.resolution.pack_key + "@" + .resolution.pack_version + " (rule " + .resolution.rule_id + ")"')"
bold "  process_instance : $PID"

step "3. Resolve the human gates via the decision API (SoD-aware)"
GATE=0
while true; do
  # Is the instance already terminal?
  ISTATUS="$(curl -sf "$RUNTIME/instances/$PID" | jq -r '.status')"
  if [ "$ISTATUS" = "completed" ] || [ "$ISTATUS" = "failed" ]; then break; fi

  TASK="$(curl -sf "$RUNTIME/hitl-tasks?status=open&process_instance_id=$PID" | jq -c '.[0] // empty')"
  if [ -z "$TASK" ]; then sleep 1; continue; fi

  TID="$(echo "$TASK" | jq -r '.task_id')"
  ELEM="$(echo "$TASK" | jq -r '.element_id')"
  MODE="$(echo "$TASK" | jq -r '.hitl_mode')"
  ROLE="$(echo "$TASK" | jq -r '.role')"
  EXCL="$(echo "$TASK" | jq -c '.sod.excluded_users // []')"
  USER="$(user_for_role "$ROLE")"
  DEC="$(decision_for_mode "$MODE")"
  GATE=$((GATE+1))

  printf "  [gate %d] %-24s mode=%-14s role=%s\n" "$GATE" "$ELEM" "$MODE" "$ROLE"
  printf "           SoD excluded_users=%s → acting as %s (decision: %s)\n" "$EXCL" "$USER" "$DEC"

  curl -sf -X POST "$RUNTIME/hitl-tasks/$TID/claim" \
       -H 'content-type: application/json' \
       -d "{\"user_id\":\"$USER\",\"role\":\"$ROLE\"}" >/dev/null
  curl -sf -X POST "$RUNTIME/hitl-tasks/$TID/decide" \
       -H 'content-type: application/json' \
       -d "{\"user_id\":\"$USER\",\"decision\":\"$DEC\"}" >/dev/null
done

step "4. Wait for the instance to reach a terminal state"
FINAL="$(poll "$RUNTIME/instances/$PID" '.status' '__terminal__' 'instance terminal' 60)"
bold "  instance status = $FINAL"

step "5. Result"
DETAIL="$(curl -sf "$RUNTIME/instances/$PID")"
echo "  outcome        : $(echo "$DETAIL" | jq -r '.outcome')"
echo "  artifacts      : $(echo "$DETAIL" | jq -c '.artifact_names')"
echo "  actor_log:"
echo "$DETAIL" | jq -r '.actor_log[] | "    - " + .element_id + " · " + .kind + " · " + .actor'

echo
echo "  checkpointed state (GET /instances/$PID/state):"
curl -sf "$RUNTIME/instances/$PID/state" | jq '{status, outcome, artifacts: (.artifacts | keys)}' | sed 's/^/    /'

echo
if [ "$FINAL" = "completed" ]; then
  bold "✅ DONE — exception $EXC_ID handled end-to-end, instance $PID completed."
else
  bold "❌ instance $PID ended '$FINAL' — see logs."
  exit 1
fi
