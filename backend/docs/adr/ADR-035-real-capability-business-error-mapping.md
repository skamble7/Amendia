# ADR-035 — Real `llm` / `mcp` / `deep_agent` business-error mapping

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-030 (error boundary events / modeled
rejection paths), ADR-020 (shared execution core + capability-worker), ADR-024 (self-descriptive MCP
descriptor). **Backlog:** closes Item A (§8, "Real llm/mcp business-error mapping") of the BPMN Deferred
Backlog.

## Context

ADR-030 delivered the error-boundary mechanism: a capability may raise `CapabilityBusinessError(error_code,
detail)`, the task-node wrapper turns it into a `boundary[element] = {"kind":"error","code":C}` delta, and the
compiled router sends it to the matching (or catch-all) error boundary, else `FAILURE_SINK` — the instance
stays running on a modeled rejection. But **only the simulation path could produce it**: the wire-repair
`apply_repair` sim raises `PAYMENT_REJECTED` under an `RJCT` steer. The three *real* (non-simulation)
capability paths could not:

1. `_execute_llm_real` → `run_real_llm` mapped every failure to a technical `CapabilityError`.
2. `_execute_mcp_real` → `HttpMcpClient.call_tool` mapped only a JSON-RPC `body["error"]` to a technical
   `RuntimeError`, and **ignored the MCP `result.isError` flag** entirely.
3. `_execute_mcp_real` / `_execute_deep_agent` would have **swallowed** a `CapabilityBusinessError` into a
   `CapabilityError` via their generic `except Exception`, even had one been raised.

So error boundaries were provable in simulation but not usable on production capabilities. This ADR wires the
three real paths to signal a modeled business error, without touching ADR-030 routing.

## Decision

**A single exception type, three real signals, no routing change.** Each real path detects a modeled outcome
and raises `CapabilityBusinessError`; the runner's existing ADR-030 routing decides match / catch-all /
unmatched→`FAILURE_SINK`. Everything else stays a technical `CapabilityError`.

- **MCP** — a modeled business error is the `tools/call` **`result.isError == true`** carrying a conventional
  **`error_code`** (in `structuredContent.error_code`, else a `content[]` JSON block; for an action-tool
  acknowledgement, `status: "rejected"` alongside the code). This is distinct from a JSON-RPC/transport error
  (`body["error"]`, HTTP failure), which stays a technical `RuntimeError → CapabilityError`. The mapping lives
  in `mcp_client.py::_raise_if_business_error`, called by `HttpMcpClient` after the protocol-error check; the
  `McpClient` Protocol documents that `call_tool` may raise `CapabilityBusinessError`. An `isError` with no
  derivable code still maps to a business error under the fallback code `MCP_TOOL_ERROR` (a catch-all can
  catch it) — `isError` is never silently downgraded to technical, per MCP semantics.

- **LLM / `deep_agent`** — the capability may return a discriminated **`{"business_error": {"code": "<CODE>",
  "detail": {...}}}`** object **in place of** its artifact. A shared detector,
  `executor/base.py::business_error_from_object`, recognises the shape (non-empty string code) and builds the
  `CapabilityBusinessError`; `run_real_llm` and `_execute_deep_agent` raise it before recording an output.
  `_execute_deep_agent` also propagates a `CapabilityBusinessError` the runner raises directly.

- **Legal codes threaded to the prompt.** The element's wired error-boundary codes (its `errorRef`s;
  catch-all dropped) are threaded through the executor as one additive `ExecutionContext.extras["error_codes"]`
  key: compiled onto `NodeContext.error_codes` in `build_node_contexts` (from
  `bpmn_model.error_boundaries`), added to `extras` in `task_runner._run_capability`, and mirrored through the
  capability-worker spec (`CapabilityRunSpec.error_codes` → `spec_to_job` → `worker_runner`) so native and
  nemoclaw stay behaviourally identical. `run_real_llm` lists these codes in the system prompt so the model
  emits a *valid* one; when empty, the prompt is unchanged (no business-error hint).

- **Non-swallowing.** `_execute_mcp_real` and `_execute_deep_agent` gained an `except CapabilityBusinessError:
  raise` before their generic `except Exception → CapabilityError`, mirroring the sim `_call`. A business error
  now propagates from all three real paths.

## Consequences

- A real MCP tool (`isError` + `error_code`) and a real `llm`/`deep_agent` capability (`business_error` object)
  each raise `CapabilityBusinessError`, which routes to the BPMN error boundary exactly as the sim path does —
  error boundaries are production-usable, not sim-only. Transport/technical failures still fail technically.
- `extras["error_codes"]` is the one additive channel; it is not a general capability-metadata refactor. The
  MCP Implementor Guideline (§4a) documents the `isError` + `error_code` convention as normative for onboarded
  servers.

## Non-goals

- No change to boundary **routing** (ADR-030 owns it), no new BPMN construct, no new execution profile.
- Real DMN, compensation, typed message-payload transforms, and the other Deferred-Backlog items remain
  deferred. `error_codes` threading is deliberately kept to the single `extras` key.
