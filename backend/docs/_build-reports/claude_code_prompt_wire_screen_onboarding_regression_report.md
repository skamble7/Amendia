# Wire "Screen" hold — debug & fix: implementation report

## 1. Outcome

**Root cause confirmed empirically on the live stack; masking bug fixed (Task 4).** The hold is a **copilot
input-map TYPE mismatch**, not a regression from the ADR-059 changeset — the bisect **exonerates** that commit.
Shipped the correct primary fix (a technical tool failure no longer masks as a silent `End_Hold`). The
happy-path-to-`End_Resolved` (acceptance #2) requires a **copilot derivation fix + re-onboard** (see §6) — I did
not force it via runtime coercion, because silently "clearing" an unscreened party is a compliance anti-pattern.

## 2. Confirmed root cause (with captured evidence)

The wire `Screen` step calls `screen_party` on the real MCP server, which **validates arguments against the
tool's CLOSED, typed `inputSchema`** (the in-process test double does not — that's the live/test divergence).
`SCREEN_INPUT.party` declares `account` as a **string** (`_typed_open`); the copilot mapped
`party ← trigger.payment.creditor`, and the wire envelope's `payment.creditor.account` is a nested **object**
`{id, scheme}`. The typed sub-field rejects the object → the tool returns `isError` with **no `error_code`** →
the runtime's fallback `CapabilityBusinessError("MCP_TOOL_ERROR")` → routed to `Bnd_Hit`, the **catch-all
error boundary** (`<errorEventDefinition/>`, no `errorRef`) → **silent `End_Hold`**. `screen_party` never sets
`isError` for a real clear/hit (a real hit flows through the output gateway), so `Bnd_Hit` only ever fires on a
technical failure — it is pure masking.

Captured MCP request/response (live `wirefix-mcp`, via `HttpMcpClient`):

| `screen_party` arguments | result |
|---|---|
| `party.account` = **string** (`"IT60X"`) | **OK, status=clear** |
| `party.account` = **object** (`{id,scheme}`) — the copilot's `party ← payment.creditor` | **isError → MCP_TOOL_ERROR** |
| full live-map shape `{party(obj acct), envelope, exception_id, hint}` | **isError → MCP_TOOL_ERROR** |

Live pack (`wire-stan`, active) `Screen` `input_map` (from Mongo): `party ← {from:trigger, path:"payment.creditor"}`,
`envelope ← payment`, `exception_id ← exception_id`, `hint ← approved_repair.justification`.

Live runtime log: instance `pi-87589d993baa469a` → `completed outcome=End_Hold` immediately after fetching
`cap.wire_stan.screen_party` schemas, no `[Screen] produced`. Dine-in `Task_ScreenAllergens` → `produced
art.stan_dine.screen_allergens_output` (green).

## 3. Bisect (Task 2) — the changeset is NOT the cause

The ADR-059 changeset is **`ed5dbd8` "removed excpetion related stuff" (179 files)**; last-good is its parent
`b34d881`. Diffing every capability/copilot/executor/handler/bpmn path across it: the **only** change is a
one-line **comment** in `agent-runtime/app/engine/task_runner.py:113` (`exception_id/…` → `trigger_id/…`). No
change to the copilot onboarding, `_mcp_arguments`, tool introspection, `screen_party`, `SCREEN_INPUT`, the wire
BPMN, or the error-boundary routing. The masking fallback (`_MCP_TOOL_ERROR`) and the copilot derivation both
**predate** ADR-059 (last touched in `62526bd` / `3060b74`). **The Screen argument shape was not altered by the
changeset** — the prompt's "regression landed in that changeset" premise is not supported by the evidence.

## 4. The fix, by file (Task 4 — masking; the correct primary fix)

`agent-runtime/app/engine/compiler.py` (the boundary router in `single_out_edge`): a `MCP_TOOL_ERROR`
(codeless, technical fallback) is now caught **only** by an EXPLICIT `errorRef` for that code — a **catch-all**
(no-`errorRef`) boundary no longer absorbs it. It falls through to `FAILURE_SINK` (instance `failed`) with a
loud `logger.error` naming the element + `last_error`. A real modeled `error_code` (or explicit errorRef) is
unchanged. Import added: `_MCP_TOOL_ERROR as MCP_TOOL_ERROR`.

Test: `agent-runtime/tests/test_error_boundary.py::test_catch_all_does_not_mask_technical_mcp_tool_error`
(+ an `MCPERR` steer that returns `isError` with no `error_code`) — asserts catch-all + `MCP_TOOL_ERROR` →
`FAILED_OUTCOME`, `last_error` contains `MCP_TOOL_ERROR`. The existing `test_catch_all_catches_a_code_with_no_
specific_boundary` (a REAL code IS still caught) is untouched.

Effect: the wire pack's mis-wired Screen now **fails visibly** with the real cause instead of a silent
compliance "hold" — satisfying acceptance #4 and making the copilot mis-derivation diagnosable.

## 5. `hint` / `recipients` wirings (Task 5)

- `Screen.hint ← approved_repair.justification` — **acceptable**. `hint` is a declared **string** and
  `justification` is a string (type-compatible, no isError). Semantically odd (`hint` is meant to steer
  clear/hit/needs_review; a free-text justification just falls through to name-based screening), but harmless.
- `Notify.recipients ← trigger.related_messages` — **a real mis-derivation (same pattern as Screen)**.
  `notify_parties.recipients` is typed **array of strings**; the generated trigger's `related_messages` is an
  **array of objects** `[{type,id,assigner_bic}]`. Live test: `recipients=[str]`/`[]` → OK `performed`;
  `recipients=[obj]` → **MCP_TOOL_ERROR**. So once Screen is fixed, `Notify` is the **next** hold. With the
  Task-4 fix it now fails visibly rather than holding.

Both are the same class of bug: the copilot maps a whole trigger path onto a **typed** tool field without
checking type compatibility; the deterministic OVER-MAP GUARD (`reconcile._capability_input_sources`) only
checks the field is *declared*, not that the source *type* matches.

## 6. Verification

- Root cause / arg shapes: direct `HttpMcpClient` calls against the **live** `wirefix-mcp` (table in §2).
- Live pack data: `process_packs` in Mongo — `wire-stan` + `stan-dine` active; Screen/Notify input_maps captured.
- Live e2e: `tools/demo_wire_repair.sh` (ports 1808x / kc 8087) drove raised→ingested→dispatched→wire-stan→gates;
  a prior wire instance logged `completed outcome=End_Hold`; dine-in `screen_allergens` `produced` its artifact
  (stan-dine green). ADR-059 routing keys/vocabulary all worked live.
- Bisect: `git show ed5dbd8 -- <capability paths>` = one comment; full 179-file stat is the vocabulary rename.
- Unit: `agent-runtime` **343 passed, 4 skipped** (incl. new masking test); `process-registry` **337 passed**.
- No git write ops; tree left dirty.

## 7. Open / for the reviewer

- **Acceptance #2 (happy path → `End_Resolved`) needs the copilot derivation fix + re-onboard**, which requires
  the copilot LLM (not runnable headless here). Recommended durable fix, at the correct layer
  (`process-registry/app/services/copilot/reconcile.py::_capability_input_sources`, and/or proposal validation):
  extend the OVER-MAP GUARD to also **detect type incompatibility** between a proposed source (resolved against
  the trigger/upstream schema) and the tool field's declared (sub)type — and **raise a high-visibility open
  question / block go-live** for `party ← payment.creditor` and `recipients ← related_messages`, rather than
  emit a mapping that holds at runtime. Prefer flagging over silent-dropping: for a **compliance screen**,
  auto-dropping `party` to force a "clear" would silently stop screening the party — worse than a hold. The
  real happy path is a correct `party`/`recipients` wiring (nested scalar leaves, or authored mapping).
- I did **not** touch the reference stub (`SCREEN_INPUT.party.account: string`) — the bisect showed the stub
  did not regress. Note, though, that `_typed_open`'s stated intent is tolerance for whole-object pass-through,
  which its rigid `account: string` undercuts; worth a separate look if the tool schema is considered authorable.
