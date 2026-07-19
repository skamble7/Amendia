# ADR-036 — Multi-instance activities (parallel + sequential)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-028 (parallel Send fan-out substrate),
ADR-027/034 (execution profiles, two-level default), ADR-032 (embedded sub-process inline-flatten).
**Backlog:** ships Deferred-Backlog item **#3** (multi-instance activities); defers MI-on-subprocess as a
new stretch line.

## Context

A `multiInstanceLoopCharacteristics` runs a task N times over a collection — "screen each party," "for each
attachment." It is the first construct that makes the parallel `Send` substrate (ADR-028) do real *per-item*
work rather than a fixed structural fan-out. Two markers exist: **parallel** MI (all N at once) and
**sequential** MI (`isSequential="true"`, one at a time with an optional early-exit).

The core difficulty is state, not control flow. `ProcessState.artifacts` is a single `merge_dicts` channel
keyed by binding name, **last-wins**. N concurrent iterations writing the same output binding would clobber —
only one would survive. So MI needs per-iteration scoping *and* a deterministic aggregation.

## Decision

**Index-scoped writes + an index-ordered join, on a dedicated scratch channel.** `merge_dicts` semantics for
ordinary bindings are untouched.

- **Model + parser (`amendia_bpmn`).** A `MultiInstance` dataclass (mirroring `ErrorBoundary`/`SubProcess`):
  `is_sequential`, `cardinality` (`<loopCardinality>`), `collection_ref` (`loopDataInputRef`), `item_name`
  (`inputDataItem`/`elementVariable`), `completion_condition`, `aggregation` (`"list"` default | `"indexed"`),
  and `on_subprocess`. `BpmnModel.multi_instance` is keyed by host activity id, populated regardless of profile
  (like every other construct dict). A task host is executable-tier only under `common_executable`.

- **Aggregation config.** The list-vs-indexed choice is the per-activity Amendia extension attribute
  `amendia:aggregation` on the `<multiInstanceLoopCharacteristics>` element (read namespace-agnostically by
  local name). Absent → `list`. No new profile knob.

- **Compilability + profile.** MI runs under `common_executable`, refused under `common_subset`
  (`bpmn_multi_instance_unsupported`); `required_profile` derives `common_executable` from `multi_instance`.
  Structural errors (even under the profile): unbounded N — neither cardinality nor collection
  (`bpmn_multi_instance_unbounded`); MI on a **sub-process** (`bpmn_multi_instance_subprocess_unsupported`, the
  deferred stretch — it compounds with the 2.6 inline-flatten); **nested** MI
  (`bpmn_multi_instance_nested_unsupported`). The `completionCondition` expression's *syntax* is validated at
  graph-compile time (like flow conditions), reusing `expr.py` — no new evaluator.

- **Compiler + state (`agent-runtime`).** A new `ProcessState.mi_results` channel (a `merge_dicts` dict) holds
  `"{host}/{i}" → that iteration's produced outputs`; unique keys mean parallel writes never collide. The host
  activity id stays the **entry** node so incoming flows resolve unchanged.
  - **Parallel MI** → a dispatch node whose conditional edge emits one `Send` per iteration (index + item +
    envelope/artifacts) to an iteration node; the iteration node writes its index-scoped result; a **join**
    node (reached by a normal edge, so it runs **once** as a barrier) reads `mi_results` in index order,
    validates each against the pinned output schema, and writes the aggregate into `artifacts`. N == 0 routes
    the dispatch straight to the join (empty aggregate).
  - **Sequential MI** → one guarded loop node: iterate 0..N-1 in order, same scoped-validate + index-ordered
    aggregation, evaluating `completionCondition` after each iteration (against the artifacts overlaid with that
    iteration's own committed output) for an early exit.
  - **Aggregation** into `artifacts`: `list` → `{binding}: [r0…rN-1]`; `indexed` → `{binding}#i` keys. By
    iteration **index**, not completion order — so parallel and sequential produce identical artifacts for
    identical inputs. Downstream gateways/capabilities consume the aggregate unchanged.

- **Scope guards (compile-time refusals, this cut).** A MI host must bind a capability; a **HITL-gated** MI
  host is refused (iterations run autonomously in `execute` mode — gated MI is deferred); a MI host that also
  carries a **boundary event** is refused (MI + boundary is deferred).

## Consequences

- "Screen each party / for each attachment" runs N times, parallel or sequential, aggregating to a list
  (default) or indexed keys, index-deterministic, with per-iteration scoping that never clobbers — reusing the
  existing `Send` substrate and `merge_dicts`/`operator.add` reducers untouched.
- The registry blocks activation of a `common_subset` pack that uses MI off the same shared
  `compilability_findings` gate the compiler raises off, so the two can't diverge.

## Deferred / non-goals

- **MI on a sub-process** (`bpmn_multi_instance_subprocess_unsupported`) — a new stretch line in the backlog;
  it compounds with the ADR-032 inline-flatten. **Nested MI** likewise refused.
- **HITL-gated MI** and **per-iteration error boundaries** — refused this cut (compile-time), deferred.
- **Parallel early-cancel** via `completionCondition` — honored for sequential only; parallel runs all N
  (cooperative cancellation of in-flight iterations is out of scope, like ADR-029's interrupting-boundary line).
- No new `completionCondition` FEEL beyond the existing `expr.py` comparison surface; no new execution profile;
  no change to `merge_dicts` for ordinary bindings; the MI scoping is contained to the construct (not a general
  scoped-variables refactor).
