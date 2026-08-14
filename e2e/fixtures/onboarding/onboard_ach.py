#!/usr/bin/env python3
"""Deterministic (copilot-free) setup of the ACH domain for the Playwright e2e — self-contained from an EMPTY,
minimally-seeded stack (identity personas + Keycloak realm + the five mcp_stub servers up; empty registry).

It creates the ``ach_exposure_cohort`` cohort definition and onboards the three ACH packs
(``ach-exposure-assess`` / ``ach-decision-enforce`` / ``ach-closeout``) to **active** by driving the registry's
TECHNICAL onboarding API (introspect the MCP servers → register caps + I/O schemas → author bindings / trigger /
triage / gateway-vars / human-artifact schemas → assemble → commit). The inference used is the registry's
rule-based ``infer_draft`` (deterministic) — NOT the LLM copilot — so every run is identical.

Key wrinkles solved (see the e2e report):
  * MCP transport enum must be ``streamable_http`` (not ``http``).
  * Trigger/close schemas in the corpus are ArtifactSchemaRegistration wrappers → use their ``json_schema``.
  * A capability binding mirrors its IO from the tool; a manual gate authors a human artifact (``outputs`` +
    a declared schema); the enforce gateway reads ``decision.rbo_decision`` (Task_CaptureDecision renamed to
    ``decision``); ``prepare_release`` consumes ``release_authorization`` so its ``records`` is array<string>.
  * **Per-pack domain** (``ach_assess`` / ``ach_enforce`` / ``ach_closeout``) so the shared ``notify_pega`` tool
    yields DISTINCT cap/artifact ids per pack — otherwise the 2nd pack's commit collides on the 1st's copies.

Idempotent: create-only-if-absent (existing active packs / an existing definition are left alone). Usage:
    python3 onboard_ach.py            # ensure the ACH domain exists (setup)
    python3 onboard_ach.py --teardown # ADR-061 clean-delete the packs + the cohort definition
Env: REGISTRY / KEYCLOAK / REALM / CLI_CLIENT / CLI_SECRET / DEV_PASSWORD (compose-host defaults).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REG = os.environ.get("REGISTRY", "http://localhost:18084").rstrip("/")
IDENTITY = os.environ.get("IDENTITY", "http://localhost:18086").rstrip("/")
KC = os.environ.get("KEYCLOAK", "http://localhost:8087").rstrip("/")
REALM = os.environ.get("REALM", "amendia-dev")
CLIENT = os.environ.get("CLI_CLIENT", "amendia-dev-cli")
SECRET = os.environ.get("CLI_SECRET", "dev-cli-secret")
PASSWORD = os.environ.get("DEV_PASSWORD", "dev-password")
CORPUS = Path(__file__).resolve().parents[3] / "backend/docs/methodology/worked-examples/ach_exposure"
COHORT_DEF = "ach_exposure_cohort"
# The persona the HITL arc drives every ACH gate as (mirrors the pytest smoke's default_persona). The ACH gate
# roles are granted to this persona post-onboarding so the browser can act on the gates.
GRANT_PERSONA = "marcus"


def _token(user: str = "priya") -> str:
    body = urllib.parse.urlencode({
        "grant_type": "password", "client_id": CLIENT, "client_secret": SECRET,
        "username": user, "password": PASSWORD, "scope": "openid",
    }).encode()
    return json.load(urllib.request.urlopen(f"{KC}/realms/{REALM}/protocol/openid-connect/token", body))["access_token"]


_T = _token()  # priya — the process owner / platform admin (onboarding + role administration)


def _http(base: str, method: str, path: str, body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token or _T}", "content-type": "application/json"})
    try:
        r = urllib.request.urlopen(req)
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200]}


def call(method: str, path: str, body=None):
    """Registry call as priya (the process owner)."""
    return _http(REG, method, path, body)


# --- human-authored artifact schemas (a manual gate's output; not introspectable) --------------------
REL = {"type": "object", "additionalProperties": False,
       "required": ["authorized", "case_id", "company", "decision", "records"],
       "properties": {"authorized": {"type": "boolean"}, "case_id": {"type": "string"},
                      "company": {"type": "string"}, "decision": {"type": "object"},
                      "records": {"type": "array", "items": {"type": "string"}}, "notes": {"type": "string"}}}
REV = {"type": "object", "additionalProperties": False, "required": ["approved", "disposition_confirmed"],
       "properties": {"approved": {"type": "boolean"},
                      "disposition_confirmed": {"type": "string", "enum": ["released", "purged"]},
                      "notes": {"type": "string"}}}
PURGE = {"type": "object", "additionalProperties": False, "required": ["authorized", "case_id"],
         "properties": {"authorized": {"type": "boolean"}, "case_id": {"type": "string"}, "notes": {"type": "string"}}}

# The ACH gates use their own domain roles (`role.ach_*`). No seeded persona holds these, so — like a real
# operator would after publishing a pack — the setup GRANTS them (see `grant_test_roles`) to the HITL persona
# (`GRANT_PERSONA`) via the identity admin API. The UI enforces role-holding (`taskEligibility`: the actor's roles
# must include the gate role), and both the Playwright arc and the pytest smoke drive every ACH gate as their
# default persona (marcus) — so all gate roles are granted to that one persona. Teardown revokes them.
PACKS = {
    "ach-exposure-assess": {
        "domain": "ach_assess", "mcp": "http://ach-assess-mcp:8075/mcp",
        "trigger": "art.ach.assess_exposure_requested", "req": "AssessExposureRequested",
        "caps": {"Task_ClassifyExposure": "classify_exposure", "Task_ClientRiskProfile": "get_client_risk_profile",
                 "Task_RecommendDisposition": "recommend_disposition", "Task_DraftUnderwriting": "draft_underwriting_message",
                 "Task_NotifyAssessed": "notify_pega"},
        "output_name": {}, "humans": {},
        "gates": {"Task_NotifyAssessed": ("approve_actions", "role.ach_exposure_assess.reviewer")},
        "gvars": [], "roles": ["role.ach_exposure_assess.reviewer"]},
    "ach-decision-enforce": {
        "domain": "ach_enforce", "mcp": "http://ach-enforce-mcp:8076/mcp",
        "trigger": "art.ach.enforce_decision_requested", "req": "EnforceDecisionRequested",
        "caps": {"Task_CaptureDecision": "capture_decision", "Task_PrepareRelease": "prepare_release",
                 "Task_RequestPurge": "request_purge", "Task_NotifyOrchestrated": "notify_pega"},
        "output_name": {"Task_CaptureDecision": "decision"},
        "humans": {"Task_AuthorizeRelease": ("release_authorization", REL, "role.ach_decision_enforce.approver"),
                   "Task_AuthorizePurge": ("purge_authorization", PURGE, "role.ach_decision_enforce.approver")},
        "gates": {},
        "gvars": [{"gateway_id": "Gateway_RboDecision", "variable": "decision.rbo_decision",
                   "source_artifact": "art.ach_enforce.capture_decision_output"}],
        "roles": ["role.ach_decision_enforce.approver"]},
    "ach-closeout": {
        "domain": "ach_closeout", "mcp": "http://ach-closeout-mcp:8077/mcp",
        "trigger": "art.ach.closeout_requested", "req": "CloseoutRequested",
        "caps": {"Task_VerifyDisposition": "verify_disposition", "Task_MarkCompleted": "mark_completed",
                 "Task_PurgeWorkingData": "purge_working_data", "Task_NotifyClosedOut": "notify_pega"},
        "output_name": {}, "humans": {"Task_ReviewArtifacts": ("review_decision", REV, "role.ach_closeout.reviewer")},
        "gates": {}, "gvars": [], "roles": ["role.ach_closeout.reviewer"]},
}


def _pack_active(name: str) -> bool:
    st, d = call("GET", f"/packs/{name}/1.0.0")
    return st == 200 and d.get("status") == "active"


def onboard(name: str, cfg: dict) -> bool:
    if _pack_active(name):
        print(f"{name}: already active (skip)")
        return True
    dom = cfg["domain"]
    call("DELETE", f"/packs/{name}")  # clean any draft from a prior partial run
    bpmn = (CORPUS / f"{name}.bpmn").read_text()
    _, s = call("POST", "/onboarding", {"pack_key": name, "version": "1.0.0", "title": name, "default_domain": dom})
    sid = s["session_id"]
    _, s = call("PUT", f"/onboarding/{sid}/bpmn", {"bpmn_xml": bpmn, "bpmn_file": f"{name}.bpmn"})
    kind = {e["element_id"]: e.get("element_kind", "serviceTask") for e in s["bpmn"]["bindable_elements"]}
    _, intro = call("POST", "/capabilities/introspect-mcp",
                    {"endpoint": cfg["mcp"], "transport": "streamable_http", "domain": dom})
    # A tool is side_effectful ONLY where THIS pack gates it with approve_actions (so the gate synthesizes
    # proposed actions → the UI's Authorize path). Ungated notify_pega (enforce/closeout) stays read_only, else
    # the assemble hitl-guard rejects a side_effectful capability with no approve_actions gate.
    gated_tools = {cfg["caps"][el] for el, (mode, _r) in cfg["gates"].items() if mode == "approve_actions"}
    tools = [{"tool": t["name"], "endpoint": cfg["mcp"], "transport": "streamable_http", "domain": dom,
              "side_effect": ("side_effectful" if t["name"] in gated_tools else "read_only"),
              "input_schema": t.get("input_schema"), "output_schema": t.get("output_schema")} for t in intro["tools"]]
    call("POST", f"/onboarding/{sid}/capabilities", {"tools": tools, "reused_capability_refs": []})
    for _el, (akey, schema, _role) in cfg["humans"].items():
        call("PUT", f"/onboarding/{sid}/artifacts",
             {"artifact_key": f"art.{dom}.{akey}", "version": "1.0.0", "title": akey, "json_schema": schema})
    # Declare the trigger BEFORE bindings: set_bindings derives each capability's field-level input_map (ADR-048),
    # and the entry capability's inputs (e.g. case_id) must map from the trigger fields. If the trigger isn't
    # declared yet, the entry map comes out empty and every downstream case_id chains back to nothing → the
    # notify_pega handback carries "unknown-case" and the pega-stub can't advance the case (A→B→C stalls).
    trig = json.loads((CORPUS / "schemas" / f"{cfg['trigger']}.json").read_text())
    call("PUT", f"/onboarding/{sid}/trigger",
         {"artifact_key": f"art.{dom}.{cfg['req'].lower()}", "version": "1.0.0", "title": "trigger",
          "json_schema": trig["json_schema"]})
    binds = []
    for el, tool in cfg["caps"].items():
        bi = {"element_id": el, "element_kind": kind.get(el, "serviceTask"), "executor_type": "capability",
              "capability_ref": f"cap.{dom}.{tool}@^1.0.0"}
        if el in cfg["output_name"]:
            bi["output_name"] = cfg["output_name"][el]
        if el in cfg["gates"]:
            mode, role = cfg["gates"][el]
            bi["hitl_mode"], bi["hitl_role"] = mode, role
        if tool == "notify_pega":
            # The Pega handback correlates on case_id. notify_pega sits AFTER a gateway join (release|purge in
            # enforce, complete|purge in closeout), so the auto-derivation may source case_id from a branch-only
            # artifact (e.g. request_purge_output) that isn't produced on the taken branch → the instance fails
            # with "input source references artifact … not produced upstream". Pin case_id to the trigger (always
            # present, branch-independent); the other notify fields default in the deterministic stub handler.
            bi["input_sources"] = {f"{tool}_input": {"fields": {"case_id": {"from": "trigger", "path": "case_id"}}}}
        binds.append(bi)
    for el, (akey, _schema, role) in cfg["humans"].items():
        binds.append({"element_id": el, "element_kind": kind.get(el, "userTask"), "executor_type": "human",
                      "role": role, "hitl_role": role, "hitl_mode": "manual",
                      "outputs": [{"name": akey, "schema_ref": f"art.{dom}.{akey}@1.0.0"}]})
    st, s = call("PUT", f"/onboarding/{sid}/bindings", {"bindings": binds})
    if st >= 300:
        print(f"{name}: BINDINGS {st} {json.dumps(s)[:200]}")
        return False
    call("PUT", f"/onboarding/{sid}/triage",
         {"triage_rules": [{"rule_id": name, "priority": 100,
                            "when": {"all": [{"field": "request_type", "op": "eq", "value": cfg["req"]}]}}]})
    call("PUT", f"/onboarding/{sid}/policies",
         {"gateway_variables": cfg["gvars"], "sod_policies": [], "roles": cfg["roles"], "role_meta": {}})
    st, s = call("POST", f"/onboarding/{sid}/assemble")
    errs = [f for f in (s.get("dry_run_report") or {}).get("findings", []) if f.get("severity") == "error"]
    if st >= 300 or errs:
        print(f"{name}: ASSEMBLE {st} errors={len(errs)} " + "; ".join(f.get("code", "") for f in errs[:6]))
        return False
    st, s = call("POST", f"/onboarding/{sid}/commit")
    call("PUT", f"/packs/{name}/1.0.0/cohort-membership", {"cohort_def_id": COHORT_DEF, "correlation_key": "case_id"})
    print(f"{name}: commit {st} {s.get('state')}")
    return st < 300 and _pack_active(name)


def ensure_cohort_definition() -> bool:
    if call("GET", f"/cohort/definitions/{COHORT_DEF}")[0] == 200:
        print(f"{COHORT_DEF}: already exists (skip)")
        return True
    f = json.loads((CORPUS / "schemas" / "cohort.ach_exposure.close.schema.json").read_text())
    graph = {
        "nodes": [{"node_id": n, "node_type": "expected"}
                  for n in ("ach-exposure-assess", "ach-decision-enforce", "ach-closeout")],
        "edges": [
            {"from_node": "__start__", "to_node": "ach-exposure-assess", "split": "and"},
            {"from_node": "ach-exposure-assess", "to_node": "ach-decision-enforce", "split": "and"},
            {"from_node": "ach-decision-enforce", "to_node": "ach-closeout", "split": "and",
             "sla": {"anchor_moment": "completion", "satisfy_moment": "arrival",
                     "deadline_seconds": 20, "at_risk_seconds": 10, "clock": "wall", "owner": "external"}},
            {"from_node": "ach-closeout", "to_node": "__close__", "split": "and"},
        ],
        "end_to_end_sla": {"deadline_seconds": 86400, "at_risk_seconds": 64800, "clock": "wall", "owner": "shared"},
    }
    st, r = call("POST", "/cohort/definitions", {
        "cohort_def_id": COHORT_DEF, "display_name": "ACH exposure", "close_schema": f["close_schema"],
        "close_correlation_path": f["close_correlation_path"], "close_outcome_path": f["close_outcome_path"],
        "expectation_graph": graph})
    print(f"{COHORT_DEF}: create {st}")
    return st in (200, 201)


def _gate_roles() -> list[str]:
    """Every distinct role the ACH gates require (gate + human bindings), across all packs."""
    roles: set[str] = set()
    for cfg in PACKS.values():
        roles.update(role for _m, role in cfg["gates"].values())
        roles.update(role for _a, _s, role in cfg["humans"].values())
    return sorted(roles)


def _persona_uid(persona: str) -> str | None:
    """The persona's Amendia user id — resolved via priya's ADMIN user list, NOT the persona's own ``/me``.

    Why not ``/me``: amendia_auth caches role resolution by ``(iss, sub)`` with a 30s TTL. Calling ``/me`` with the
    persona's token BEFORE the grant lands would cache the persona's PRE-grant roles for 30s — and the webui login
    (seconds later, in global-setup) would then snapshot those stale roles for the whole run, leaving every HITL
    gate un-actionable. Resolving through priya's admin call touches only priya's cache entry, so the persona's
    first resolution (at login) reads the freshly-granted roles. Persona email is the identity seed key."""
    email = f"{persona}@amendia.dev"
    st, users = _http(IDENTITY, "GET", "/users")
    if st != 200 or not isinstance(users, list):
        print(f"grant: could not list users (HTTP {st}) — skipping role grant")
        return None
    uid = next((u.get("amendia_user_id") for u in users if u.get("email") == email), None)
    if not uid:
        print(f"grant: no identity user with email {email}")
    return uid


def _persona_email(persona: str) -> str:
    return f"{persona}@amendia.dev"  # the identity seed/JIT key


def grant_test_roles() -> None:
    """Give the HITL persona (marcus) the ACH gate roles so the browser can act on the gates.

    PRIMARY — pending-stage by email (`POST /pending-role-assignments {email, roles}`): identity materialises staged
    roles onto the user at JIT-provision (first login). global-setup runs this BEFORE the persona logins, so marcus
    logs in ALREADY holding the roles. This is the only path that works on a genuinely clean stack — where marcus is
    not provisioned yet, so priya's admin `GET /users` can't find him — and it never mints marcus's token / calls his
    `/me`, preserving the no-cache-poison property (see `_persona_uid`, gotcha #5).

    FALLBACK — already provisioned (e.g. a reused `--keep` stack): staging returns 409 `user_exists`, so resolve the
    uid via priya's admin `GET /users` and grant each role via `POST /users/{uid}/roles` (idempotent; 409 = held)."""
    roles = _gate_roles()
    email = _persona_email(GRANT_PERSONA)
    st, _ = _http(IDENTITY, "POST", "/pending-role-assignments", {"email": email, "roles": roles})
    if st == 201:
        print(f"stage: {GRANT_PERSONA} pending += {roles} (materialises at first login)")
        return
    if st != 409:  # 409 user_exists is the expected already-provisioned case; anything else still falls back
        print(f"stage: unexpected HTTP {st} staging {email} — falling back to admin grant")
    uid = _persona_uid(GRANT_PERSONA)
    if not uid:
        print(f"grant: no uid for '{GRANT_PERSONA}' — skipping role grant (HITL gates may be un-actionable)")
        return
    for role in roles:
        st, _ = _http(IDENTITY, "POST", f"/users/{uid}/roles", {"role": role})
        print(f"grant: {GRANT_PERSONA} += {role} -> {st}{' (already held)' if st == 409 else ''}")


def revoke_test_roles() -> None:
    """Teardown: leave identity as found. Delete any pending stage (404 is fine — it was consumed at the persona's
    first login, or never created on the fallback path) AND revoke the roles from the provisioned user if present."""
    email = _persona_email(GRANT_PERSONA)
    st, _ = _http(IDENTITY, "DELETE", f"/pending-role-assignments/{email}")
    print(f"revoke: pending stage for {email} -> {st}")
    uid = _persona_uid(GRANT_PERSONA)
    if not uid:
        return
    for role in _gate_roles():
        st, _ = _http(IDENTITY, "DELETE", f"/users/{uid}/roles/{role}")
        print(f"revoke: {GRANT_PERSONA} -= {role} -> {st}")


def teardown() -> None:
    revoke_test_roles()
    call("DELETE", f"/cohort/definitions/{COHORT_DEF}")
    for name in PACKS:
        call("DELETE", f"/packs/{name}")  # ADR-061 clean-delete (audit-first)
    print("teardown: removed cohort definition + ACH packs")


def main() -> int:
    if "--teardown" in sys.argv:
        teardown()
        return 0
    ok = ensure_cohort_definition()
    for name, cfg in PACKS.items():
        ok = onboard(name, cfg) and ok
    grant_test_roles()  # after publishing — grant the ACH gate roles to the HITL persona (marcus)
    print("ACH domain ready" if ok else "ACH domain INCOMPLETE (execution journeys will skip)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
