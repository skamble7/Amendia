# Claude Code prompt — split the ACH MCP stub into one server per segment

Refactor the single combined `ach_exposure` MCP stub into **three independent MCP servers, one per Amendia
segment**, each exposing only its own segment's tools (plus the shared `notify_pega` handback). This is the ACH
cohort worked example (ADR-063); the segments will each point at their own MCP server at onboarding. No tool
behaviour changes — this is a repackaging, reusing the existing handlers + schemas verbatim.

## Why

Today `mcp_stub/servers/ach_exposure/` exposes all 11 tools from one server. Splitting per segment isolates each
segment's capabilities (independently deployable, matches the one-server-per-domain pattern of
`wire_transfer_exception` / `restaurant_dinein`, and is truer to a real deployment where each segment's tools
could belong to a different system).

## The split (keep tool names, schemas, and handler logic identical)

| New server dir | Package | Tools | Port | Network alias |
|----------------|---------|-------|------|---------------|
| `mcp_stub/servers/ach_exposure_assess` | `ach_exposure_assess_mcp` | `classify_exposure`, `get_client_risk_profile`, `recommend_disposition`, `draft_underwriting_message`, `notify_pega` | 8075 | `ach-assess-mcp` |
| `mcp_stub/servers/ach_decision_enforce` | `ach_decision_enforce_mcp` | `capture_decision`, `prepare_release`, `request_purge`, `notify_pega` | 8076 | `ach-enforce-mcp` |
| `mcp_stub/servers/ach_closeout` | `ach_closeout_mcp` | `verify_disposition`, `mark_completed`, `purge_working_data`, `notify_pega` | 8077 | `ach-closeout-mcp` |

`notify_pega` (the Pega handback) is in **all three** — each segment's BPMN ends with it, so each pack binds its
own server's copy.

## Read first (reuse, don't rewrite)

- `mcp_stub/servers/ach_exposure/src/ach_exposure_mcp/{schemas.py, handlers.py, server.py, __init__.py}` — the
  existing, tested source. The tool specs (`TOOLS`), schemas, and handlers are correct and guideline-compliant
  (acknowledgement floor on action tools, enum decision fields, `capture_decision.rbo_decision` gateway key,
  `notify_pega` POST) — carry them over unchanged.
- `mcp_stub/servers/wire_transfer_exception/` — the standalone-server layout to mirror per server
  (`pyproject.toml`, `Dockerfile`, `tests/`, `src/<pkg>/`).
- `mcp_stub/deploy/docker-compose.yml` — currently one `ach-exposure` service; replace it with three.

## Tasks

1. **Create the three server dirs** in the table, each self-contained like the wire/dine servers:
   `pyproject.toml` (name/script/package per row), `Dockerfile` (its port), `README.md`, `tests/test_server.py`,
   and `src/<pkg>/{__init__.py, server.py, handlers.py, schemas.py}`.
2. **Carry over the code per segment.** Each server's `handlers.py`/`schemas.py` contains ONLY its segment's
   tools + `notify_pega`, lifted verbatim from the combined server (same function bodies, same schema objects,
   same `check_compliance`, same `_dig`/helpers, same `notify_pega` POST-to-`PEGA_STUB_URL`). `server.py` is the
   same low-level `Server` + streamable-HTTP `/mcp` + `/health`, with its own `SERVER_NAME` and default `PORT`.
   - Keep the shared helpers/`notify_pega` **duplicated per server** (they're small and it keeps each server
     standalone, matching the wire/dine pattern) — do NOT introduce a shared runtime package unless it's clearly
     cleaner; if you do, keep it a tiny `mcp_stub/servers/_ach_common` importable at build time without breaking
     each server's independent `pip install .`.
3. **Remove the combined server** `mcp_stub/servers/ach_exposure/` (superseded). It's a git-tracked delete —
   remove the directory; leave staging to the operator.
4. **Compose:** replace the single `ach-exposure` service with three (`ach-exposure-assess` :8075 alias
   `ach-assess-mcp`, `ach-decision-enforce` :8076 alias `ach-enforce-mcp`, `ach-closeout` :8077 alias
   `ach-closeout-mcp`), each with `PEGA_STUB_URL: "${PEGA_STUB_URL:-http://pega-stub:9095}"` and joined to the
   external `amendia` network, mirroring the existing block.
5. **Tests per server:** the same offline checks scoped to that server's tools — `check_compliance` passes, each
   handler's output validates against its `outputSchema`, action tools carry the ack floor, and (enforce server)
   `capture_decision.rbo_decision` is the gateway key. Keep the steering/determinism assertions relevant to each.
6. **Update the worked-example README** `backend/docs/methodology/worked-examples/ach_exposure/README.md`: the
   capabilities table now maps each segment to **its own** MCP server URL (`http://ach-assess-mcp:8075/mcp`,
   `http://ach-enforce-mcp:8076/mcp`, `http://ach-closeout-mcp:8077/mcp`) — so onboarding points each pack at the
   right server. (The BPMN + trigger schemas are unchanged.)

## Do not

- Do not change any tool's name, input/output schema, or handler behaviour — onboarding + the Pega stub depend
  on them exactly as-is. This is packaging only.
- Do not touch the `pega_stub`, the segment BPMN/trigger schemas, the trigger ingress, or any backend service.
- No git writes — leave the tree dirty; the operator owns commits (including staging the directory delete).

## Acceptance

- Three servers build and serve their own tool subset at `/mcp` (`tools/list` returns exactly that segment's
  tools + `notify_pega`); `/health` reports the right count.
- `docker compose -f mcp_stub/deploy/docker-compose.yml up --build` brings up all three on the network at their
  aliases; wire/dine services unaffected.
- `pytest` green in each new server; the combined `ach_exposure` server is gone.
- The worked-example README points each segment at its own server URL.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ach_split_mcp_per_segment_report.md` (uncommitted): (1)
outcome one-liner; (2) the three servers (dirs, ports, aliases, tool lists) and confirmation the tool
schemas/handlers are byte-for-byte the combined server's; (3) whether helpers were duplicated or shared and why;
(4) compose + README updates; (5) verification (per-server `tools/list` count, pytest) + results; (6) note the
combined-server removal. Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Packaging-only refactor; reuse the existing tested
code verbatim. Stay inside `mcp_stub/`.
