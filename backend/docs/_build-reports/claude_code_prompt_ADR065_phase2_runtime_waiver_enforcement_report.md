# ADR-065 P2 — runtime enforcement of the side-effect gate (agent-runtime)

**Outcome: DONE and green.** The runtime no longer trusts the manifest blindly: a side-effectful capability at
hitl `none` (and a side-effectful human-assist that runs before its gate) now fails **closed** with
`side_effect_ungated` unless the binding carries the operator's P1 waiver — the tool is never called. A catch-all
error boundary cannot mask it, and a side-effectful multi-instance host is refused at compile. agent-runtime only;
no registry / contracts / webui / GLEA change. Tree left dirty.

## 1. Where the waiver is threaded, and its shape on `NodeContext`

`NodeContext` gained one field (`task_runner.py`, in the dataclass):

```python
side_effect_waiver: Optional[Any] = None
```

Kept a **structured value** (the contract `SideEffectWaiver`, or `None`) — *not* a bool — so P4 can add
`waived_by` / `waived_at` / `waived_capability_id` without reshaping `NodeContext`. It is populated in
`bundle.py::build_node_contexts:209`:

```python
side_effect_waiver=getattr(mb, "side_effect_waiver", None),
```

read defensively so a bundle built from an older cached manifest (no such field) doesn't explode. It is also
carried through `call_activity.py::_scope_ctx:108` — without that, a legitimately-waived side-effectful task
inside an *inlined* call activity would fail closed spuriously.

## 2. Enforcement points

| # | File:line | Reason code | Fires when |
|---|---|---|---|
| D2 | `task_runner.py:434-441` (mode-`none` capability branch, immediately after the `_is_deep_agent` check) | `side_effect_ungated` | `_side_effect(ctx.descriptor) == "side_effectful"` and `getattr(ctx, "side_effect_waiver", None) is None` — raised **before** `_produce_outputs(mode="execute")`, so the tool is never called. With a waiver: run + `logger.info` the justification (an ungated action is never silent in the log). |
| D3 | `task_runner.py:855-909` (`_run_manual`, before the assist runs in `mode="execute"`) | `side_effect_ungated` | the assist descriptor is `side_effectful` **and** `not hitl_mode_at_least(ctx.hitl_mode, "approve_actions")` and no waiver. Mirrors the P1 registry rule `assist_side_effect_requires_approve_actions` exactly (same floor, same waivability). Human executors route to `_run_manual` *before* the `hitl_mode` dispatch, so D2 does not cover this — it needs its own check. |
| D5 | `compiler.py:283-288` (multi-instance host loop, before the existing hitl-none check) | `CompilerError` | the MI host's descriptor is `side_effectful` — waiver or not (ADR-065 Part E). Defense in depth for a manifest that didn't come through the registry's `multi_instance_side_effect_unsupported`. |

D2 and D3 mirror the adjacent `_is_deep_agent` fail-closed check (`task_runner.py:437`, `reason="deep_agent_ungated"`) rather than inventing a new pattern.

## 3. Deliverable 4 — the boundary-exclusion mechanism (reused, not rebuilt)

The wire-screen bug was a codeless runtime failure that a **catch-all** boundary re-labelled as a business
outcome. `side_effect_ungated` must be structurally incapable of that. The mechanism I found and reused:

**Only a `CapabilityBusinessError` ever becomes a maskable boundary entry.** In the node wrapper:

```python
# task_runner.py:161-173
except CapabilityBusinessError as exc:
    delta = {
        "boundary": {ctx.element_id: {"kind": "error", "code": exc.error_code}},
        ...
```

That `boundary[...] = {kind: "error", code}` entry is the *only* thing the boundary router consumes
(`compiler.py:414-434`). A **`NodeExecutionError`** — which is what `side_effect_ungated` (and `deep_agent_ungated`)
raise — is **not** caught there. It propagates out of the node to the engine:

```python
# engine.py:419-426
except Exception as exc:  # any node failure terminates the instance
    reason = getattr(exc, "reason", "node_error")
    ...
    await self._fail(instance, reason, str(exc))
```

So it never produces a `boundary` entry, the router never runs for it, and **no boundary — catch-all or explicit
`errorRef` — can catch it.** This is the same reason `deep_agent_ungated` is already unmaskable; I reused it by
raising the same exception class, adding nothing to the router. (The router's existing `technical = code ==
MCP_TOOL_ERROR` guard at `compiler.py:433` is the *weaker* sibling — it excludes a failure that *did* produce a
boundary code; `NodeExecutionError` is excluded one step earlier, by never producing one.)

**Proof:** `test_catch_all_boundary_does_not_swallow_side_effect_ungated` attaches a catch-all error boundary to
`Task_ApplyRepair`, drops that side-effectful binding to hitl `none` with no waiver, and asserts `drive()` raises
with `reason == "side_effect_ungated"` (had the catch-all swallowed it, the outcome would be `End_Returned`). This
is the assertion that would have caught the wire-screen class of bug.

## 4. Deliverable 5 — the timer-boundary confirmation

**Confirmed: `compiler.py:189-197` needs no change.** The interrupting-timer-boundary refusal keys on
`side_effectful` **independently of the gate** (`compiler.py:193-197` raises for any side-effectful host; the
`hitl != "none"` refusal at `:189-192` is separate). Before P1 a side-effectful task could not be at `none`, so
that side-effect refusal was unreachable for a legal manifest; P1's waiver now makes `none` legal, but a waived
side-effectful task with a timer boundary still hits the `:193-197` refusal. Allowing `none` did **not** widen the
timer path — the side-effect refusal already covered it. (Same structure at `:205-215` for scope timers.)

## 5. Verification

Commands from `backend/services/agent-runtime` (`uv run --extra dev pytest`):

| Check | Result |
|---|---|
| agent-runtime full suite | **405 collected, exit 0** (was 397 → +8 new tests; zero failures) |
| new file `test_side_effect_waiver_runtime.py` | **8 passed** (D2 ×3, D3 ×3, D4 ×1, D5 ×1) |
| `libs/amendia_contracts` | **9 passed** (P2 imports `hitl_mode_at_least` / `SideEffect` / `SideEffectWaiver` from it but changes nothing) |
| process-registry | **untouched by P2** — its working tree carries only the reviewed-closed P1 changes; P2's entire diff is in agent-runtime (`bundle.py`, `call_activity.py`, `compiler.py`, `task_runner.py`, + the new test) |
| OpenAPI / generated types | **no change** — P2 adds no API surface; `registry.json`/`registry.ts` remain modified only by P1's additive field |

**Tool-never-called** is asserted directly, not via instance state: a `_Spy` executor counts `execute` calls;
`test_side_effectful_none_no_waiver_fails_closed_tool_never_called` and the assist equivalent assert `spy.calls ==
0` on the failure path, and `== 1` on the waived path.

**Existing packs unaffected — and why it is guaranteed.** Every side-effectful capability in the seed
(`apply_repair`, `execute_return`, `notify_parties`) is bound at `approve_actions`; none is at `none`, so the new
check cannot fire on them (`test_read_only_none_is_unaffected` and the full green suite confirm). More generally:
before P1 an ungated side-effectful binding could not be *activated*, so every pack in the field is gated or
read-only — the check can only fire on a new/hand-edited manifest, never on anything already live.

## 6. For P3 / P4

- **P3 (UI):** a node that fails `side_effect_ungated` is a **platform-integrity failure, not a business hold** —
  surface it as "a side-effectful step was left ungated with no operator waiver; re-activate this pack through the
  registry", distinct from a modelled business outcome. When a node runs *under* a waiver, the UI may want to badge
  it "ran ungated (operator waiver)" with the justification.
- **P4 (GLEA):** the audit payload should carry, on the waived-and-run path, `element_id` + `capability_id` +
  `justification` (already logged at INFO here), and — once the waiver object gains them — `waived_by` /
  `waived_at`. On the failure path, `reason="side_effect_ungated"` + element + capability. The waiver's trust at the
  registry boundary is emission-side, not signed (see the P1-followup report §5); GLEA is where a durable record of
  who waived what belongs.

## 7. Operator note (not live until rebuilt)

Not live until `docker compose build agent-runtime` (+ restart). Also: the runtime holds a **non-evicting bundle
cache** — a stack that has already loaded a pack will keep serving `NodeContext`s built *before* this change (no
`side_effect_waiver` field, and — irrelevant for existing gated packs — no enforcement) until restart. A restart
is required for the re-threaded field and the new checks to take effect, not just an image rebuild.
