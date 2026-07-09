#!/usr/bin/env bash
# tools/demo_wire_repair.sh
#
# End-to-end acceptance narrative for the wire-repair-standard vertical slice,
# now also the AUTH acceptance test:
#   generate → ingest → resolve → dispatch → accept → run (HITL gates via API) → completed.
#
# Every call carries a real Keycloak bearer minted via the dev-only CLI client
# (amendia-dev-cli). Identity + roles come from the token — the claim/decide bodies
# no longer carry {user_id, role}. Roles map to personas: analyst gates → riya,
# approver gates → marcus. `decided_by` in the actor log shows Amendia `usr-…` ids.
#
# Works whether the compat-stub flags are on (compose default) or off
# (docker compose -f docker-compose.yml -f docker-compose.auth-strict.yml up):
# a present, valid bearer is always honoured.
#
# Assumes the compose stack is up:
#   docker compose -f backend/deploy/docker-compose.yml up --build
#
# Requires: curl, jq.  Override endpoints with STUB/INGESTOR/RUNTIME/KEYCLOAK env vars.
set -euo pipefail

STUB="${STUB:-http://localhost:8081}"
INGESTOR="${INGESTOR:-http://localhost:8082}"
RUNTIME="${RUNTIME:-http://localhost:8083}"
KEYCLOAK="${KEYCLOAK:-http://localhost:8087}"
REALM="${REALM:-amendia-dev}"
CLI_CLIENT="${CLI_CLIENT:-amendia-dev-cli}"
CLI_SECRET="${CLI_SECRET:-dev-cli-secret}"
DEV_PASSWORD="${DEV_PASSWORD:-dev-password}"
REASON="${1:-AC01}"

command -v jq >/dev/null || { echo "jq is required"; exit 1; }

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

# --- mint a bearer for a Keycloak user via the dev CLI client (password grant) ---
mint_token() {
  local username="$1"
  curl -sf "$KEYCLOAK/realms/$REALM/protocol/openid-connect/token" \
    -d grant_type=password \
    -d client_id="$CLI_CLIENT" \
    -d client_secret="$CLI_SECRET" \
    -d username="$username" \
    -d password="$DEV_PASSWORD" \
    -d scope=openid \
    | jq -r '.access_token'
}

step "0. Mint dev tokens (Keycloak $REALM via $CLI_CLIENT)"
TOKEN_RIYA="$(mint_token riya)"
TOKEN_MARCUS="$(mint_token marcus)"
[ -n "$TOKEN_RIYA" ] && [ "$TOKEN_RIYA" != "null" ] || { echo "failed to mint riya token"; exit 1; }
[ -n "$TOKEN_MARCUS" ] && [ "$TOKEN_MARCUS" != "null" ] || { echo "failed to mint marcus token"; exit 1; }
bold "  minted tokens for riya (analyst) and marcus (approver)"

# riya proves JIT-provisioning + roles via /me on the identity service (optional).
if ME="$(curl -sf -H "Authorization: Bearer $TOKEN_RIYA" http://localhost:8086/me 2>/dev/null)"; then
  echo "  riya /me → $(echo "$ME" | jq -c '{amendia_user_id, roles}')"
fi

token_for_role() {
  case "$1" in
    role.payments.ops_approver) echo "$TOKEN_MARCUS" ;;
    *)                          echo "$TOKEN_RIYA" ;;
  esac
}

# curl helpers that always carry a bearer.
rget() { curl -sf -H "Authorization: Bearer $1" "$2"; }  # rget <token> <url>

decision_for_mode() {
  # manual gates are "completed"; every other mode is "approved".
  [ "$1" = "manual" ] && echo "complete" || echo "approve"
}

poll() { # poll <token> <url> <jq-filter> <want> <label> [max]
  local tok="$1" url="$2" filt="$3" want="$4" label="$5" max="${6:-60}" i=0 got=""
  while [ "$i" -lt "$max" ]; do
    got="$(rget "$tok" "$url" 2>/dev/null | jq -r "$filt" 2>/dev/null || true)"
    [ "$got" = "$want" ] && { echo "$got"; return 0; }
    case "$want" in
      __terminal__) [ "$got" = "completed" ] || [ "$got" = "failed" ] && { echo "$got"; return 0; } ;;
    esac
    sleep 1; i=$((i+1))
  done
  echo "TIMEOUT waiting for $label (last='$got')" >&2
  return 1
}

step "1. Generate a wire exception (reason_code=$REASON) at the stub — with riya's bearer"
GEN="$(curl -sf -X POST "$STUB/exceptions/generate" \
        -H "Authorization: Bearer $TOKEN_RIYA" \
        -H 'content-type: application/json' \
        -d "{\"reason_code\":\"$REASON\",\"count\":1}")"
EXC_ID="$(echo "$GEN" | jq -r '.created[0].exception.exception_id')"
RK="$(echo "$GEN" | jq -r '.created[0].routing_key')"
bold "  exception_id = $EXC_ID   (published on $RK)"

step "2. Wait for the ingestor to ingest → resolve → dispatch → accepted"
poll "$TOKEN_RIYA" "$INGESTOR/ingestions/$EXC_ID" '.status' 'accepted' 'ingestion=accepted' 60 >/dev/null
ING="$(rget "$TOKEN_RIYA" "$INGESTOR/ingestions/$EXC_ID")"
PID="$(echo "$ING" | jq -r '.process_instance_id')"
echo "  ingestion status : $(echo "$ING" | jq -r '.status')"
echo "  resolved pack    : $(echo "$ING" | jq -r '.resolution.pack_key + "@" + .resolution.pack_version + " (rule " + .resolution.rule_id + ")"')"
bold "  process_instance : $PID"

step "3. Resolve the human gates via the decision API (identity + roles from the token)"
GATE=0
while true; do
  ISTATUS="$(rget "$TOKEN_RIYA" "$RUNTIME/instances/$PID" | jq -r '.status')"
  if [ "$ISTATUS" = "completed" ] || [ "$ISTATUS" = "failed" ]; then break; fi

  TASK="$(rget "$TOKEN_RIYA" "$RUNTIME/hitl-tasks?status=open&process_instance_id=$PID" | jq -c '.[0] // empty')"
  if [ -z "$TASK" ]; then sleep 1; continue; fi

  TID="$(echo "$TASK" | jq -r '.task_id')"
  ELEM="$(echo "$TASK" | jq -r '.element_id')"
  MODE="$(echo "$TASK" | jq -r '.hitl_mode')"
  ROLE="$(echo "$TASK" | jq -r '.role')"
  EXCL="$(echo "$TASK" | jq -c '.sod.excluded_users // []')"
  TOK="$(token_for_role "$ROLE")"
  WHO="$([ "$ROLE" = "role.payments.ops_approver" ] && echo marcus || echo riya)"
  DEC="$(decision_for_mode "$MODE")"
  GATE=$((GATE+1))

  printf "  [gate %d] %-24s mode=%-14s role=%s\n" "$GATE" "$ELEM" "$MODE" "$ROLE"
  printf "           SoD excluded_users=%s → acting as %s (decision: %s, no role in body)\n" "$EXCL" "$WHO" "$DEC"

  # claim: identity comes from the bearer; body is empty.
  curl -sf -X POST "$RUNTIME/hitl-tasks/$TID/claim" \
       -H "Authorization: Bearer $TOK" \
       -H 'content-type: application/json' -d '{}' >/dev/null
  # decide: only the decision travels in the body.
  curl -sf -X POST "$RUNTIME/hitl-tasks/$TID/decide" \
       -H "Authorization: Bearer $TOK" \
       -H 'content-type: application/json' \
       -d "{\"decision\":\"$DEC\"}" >/dev/null
done

step "4. Wait for the instance to reach a terminal state"
FINAL="$(poll "$TOKEN_RIYA" "$RUNTIME/instances/$PID" '.status' '__terminal__' 'instance terminal' 60)"
bold "  instance status = $FINAL"

step "5. Result"
DETAIL="$(rget "$TOKEN_RIYA" "$RUNTIME/instances/$PID")"
echo "  outcome        : $(echo "$DETAIL" | jq -r '.outcome')"
echo "  artifacts      : $(echo "$DETAIL" | jq -c '.artifact_names')"
echo "  actor_log (decided_by shows Amendia usr-… ids):"
echo "$DETAIL" | jq -r '.actor_log[] | "    - " + .element_id + " · " + .kind + " · " + .actor'

echo
echo "  checkpointed state (GET /instances/$PID/state):"
rget "$TOKEN_RIYA" "$RUNTIME/instances/$PID/state" | jq '{status, outcome, artifacts: (.artifacts | keys)}' | sed 's/^/    /'

echo
if [ "$FINAL" = "completed" ]; then
  bold "✅ DONE — exception $EXC_ID handled end-to-end with real bearers, instance $PID completed."
else
  bold "❌ instance $PID ended '$FINAL' — see logs."
  exit 1
fi
