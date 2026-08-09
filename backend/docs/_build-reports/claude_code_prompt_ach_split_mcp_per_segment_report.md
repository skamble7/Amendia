# Split the ACH MCP stub into one server per segment: report

## 1. Outcome

The single combined `ach_exposure` MCP server is replaced by **three independent servers, one per Amendia
segment**, each exposing only its own segment's tools plus the shared `notify_pega` handback. Packaging-only —
tool names, schemas, and handler logic are carried over verbatim. All three build via the MCP SDK and pass their
scoped tests; the combined server is removed.

## 2. The three servers

| Dir (`mcp_stub/servers/…`) | Package | Port | Alias | Tools |
|---|---|---|---|---|
| `ach_exposure_assess` | `ach_exposure_assess_mcp` | 8075 | `ach-assess-mcp` | `classify_exposure`, `get_client_risk_profile`, `recommend_disposition`, `draft_underwriting_message`, `notify_pega` (5) |
| `ach_decision_enforce` | `ach_decision_enforce_mcp` | 8076 | `ach-enforce-mcp` | `capture_decision`, `prepare_release`, `request_purge`, `notify_pega` (4) |
| `ach_closeout` | `ach_closeout_mcp` | 8077 | `ach-closeout-mcp` | `verify_disposition`, `mark_completed`, `purge_working_data`, `notify_pega` (4) |

Each is self-contained like the wire/dine servers: `pyproject.toml` (own name/script/package), `Dockerfile` (own
port), `README.md`, `tests/test_server.py`, `src/<pkg>/{__init__, server, handlers, schemas}.py`. Each
`server.py` is the same low-level `Server` + streamable-HTTP `/mcp` + `/health`, with its own `SERVER_NAME` and
default `PORT`. Onboard each segment against `http://ach-assess-mcp:8075/mcp` / `…ach-enforce-mcp:8076…` /
`…ach-closeout-mcp:8077…`.

**Byte-for-byte carry-over.** Every tool's `input_schema`/`output_schema` object and every handler body is
lifted unchanged from the combined server — same `_dig`/`_num`/`_case_id`/`_company`/`_hash`/`action_id`, same
`_FIXED_TS`, same schema builders (`_input`/`_output`/`_action_output`/`_typed_open`/the ack floor), same
`capture_decision.rbo_decision` enum gateway key, same `notify_pega` POST-to-`PEGA_STUB_URL`, same
`check_compliance`. Only the `TOOLS` list, `ACTION_TOOLS` set, `SERVER_NAME`, default port, and (in schemas) the
per-segment schema objects differ; unused nested shapes (`_CASE`/`_AMOUNTS`) were dropped from the enforce/
closeout schema modules.

## 3. Helpers: duplicated, not shared

The shared helpers + `notify_pega` are **duplicated per server** (each has its own copy), matching the
one-server-per-domain pattern of `wire_transfer_exception` / `restaurant_dinein`. They're small, and duplication
keeps every server independently `pip install .`-able with no cross-package build dependency — no
`_ach_common` runtime package was introduced.

## 4. Compose + README

- `mcp_stub/deploy/docker-compose.yml`: the single `ach-exposure` service (`:8075`, alias `ach-mcp`) is replaced
  by three — `ach-exposure-assess` (`:8075`/`ach-assess-mcp`), `ach-decision-enforce` (`:8076`/`ach-enforce-mcp`),
  `ach-closeout` (`:8077`/`ach-closeout-mcp`) — each with `PEGA_STUB_URL: "${PEGA_STUB_URL:-http://pega-stub:9095}"`
  on the external `amendia` network. The header comment's introspect-URL list is updated to the three segment
  servers. Wire/dine services untouched.
- `backend/docs/methodology/worked-examples/ach_exposure/README.md`: the capabilities section is now a table
  mapping each segment to **its own** MCP server URL (BPMN + trigger schemas unchanged).

## 5. Verification

- Per-server `pytest` (`uv run --extra test pytest`): `ach_exposure_assess` **7 passed**, `ach_decision_enforce`
  **6 passed**, `ach_closeout` **6 passed** — each asserts the exact tool set, `check_compliance`, every
  handler's output validates against its `outputSchema`, action tools carry the ack floor, determinism, and
  (enforce) the `capture_decision.rbo_decision` gateway enum.
- SDK wiring smoke (`build_server()` + `create_app()` per server): all three build; `tools/list` count = **5 / 4
  / 4** respectively; `SERVER_NAME` + default port correct (`ach-exposure-assess`:8075, `ach-decision-enforce`:8076,
  `ach-closeout`:8077). `/health` reports the same count.
- Residual-reference sweep: no live code/compose references the removed `ach_exposure_mcp` / `ach-mcp` alias
  (only historical `_build-prompts/` docs).

## 6. Combined-server removal

`mcp_stub/servers/ach_exposure/` was deleted (a git-tracked delete — staging left to the operator per the working
agreement). No backend service, the `pega_stub`, the segment BPMN/trigger schemas, or the trigger ingress were
touched — this is packaging only.
