# ADR-038 — Collection-reduction / summary capability (`reduce` kind)

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-036 (multi-instance — produces list
artifacts), ADR-037 (native DMN — the `decision` kind pattern + the bounded FEEL unary-test surface).
**Backlog:** ships the *collection-reduction / summary capability* deferred line (§8, noted at ADR-036/037).

## Context

Multi-instance activities (ADR-036) aggregate into a **list** artifact (`{binding: [r0, r1, …]}`), and MI
`COLLECT` likewise. But nothing can branch on a list: gateway conditions (`expr.py`) and DMN unary tests
operate on **scalars** by dotpath. So a process can "screen each party" but can't ask "is *any* party a hit?"
or "are *all* approved?" — the exact gap called out when MI and native DMN shipped. Widening `expr.py` or the
DMN surface into a collection-query language is the wrong answer (it fights their deliberately bounded,
auditable design). The right answer is a small capability that **collapses a list into a scalar/summary**.

## Decision

**A new `reduce` capability kind, mirroring `decision` (ADR-037), reusing the DMN predicate surface.**

- **`reduce` capability kind (contract).** A `ReduceRuntime` carries an inline, normalized `config`, pinned
  with the capability like any kind; `side_effect` always `read_only`. It binds an **ordinary `serviceTask`**
  (capability executor category) — so there is **no BPMN/compiler/parser/profile change**, purely contract +
  evaluator + runtime kind + validation + seed.

- **Evaluator (`amendia_bpmn.reduce`, shared by registry + runtime — one implementation, like `dmn.py`).**
  `parse_reduce_config` / `evaluate_reduce` / `validate_reduce`, pure over `(config, inputs)`. The per-item
  `predicate` **reuses the bounded DMN unary-test surface** (`parse_unary_test` / `_test_matches`) — one FEEL
  surface across the platform, no new mini-language. Config: `source` (dotpath to the list, rooted on the
  binding inputs; `"."`/empty = the sole input), `item_path` (dotpath into each item, absent → the item),
  `predicate` (defines a "matching" item), `op`, `output_field`. Ops:
  - **quantifiers** `any` / `all` / `none` (over the predicate; empty list → `any=false`, `all=true`,
    `none=true` vacuously) → boolean;
  - **`count`** (matching items with a predicate, else all items);
  - **numeric** `sum` / `min` / `max` / `avg` (over the `item_path` values; empty → `sum=0`/`avg=0`,
    `min`/`max` → a runtime error);
  - **positional** `first` / `last` (the matching item's `item_path` value, or the raw first/last if no
    predicate; empty/no-match → `null`).

- **Runtime (`_execute_reduce`).** Resolve `source` from the bound inputs → a list, run `evaluate_reduce`,
  produce the summary artifact (host-validated against the pinned output schema). `source` not resolving to a
  list, a numeric op on an empty list, or a non-numeric value is a **technical** `CapabilityError` — a config
  that passed validation but misfires is a bug, not a modeled outcome, so it is **never routed to an error
  boundary** (same discipline as `_execute_decision`).

- **Validation (registry, sibling to `decision.py`).** Stage 3 resolves `reduce` like any kind. New
  error-severity codes: `reduce_unknown_op`; `reduce_bad_predicate` (predicate outside the bounded surface —
  reuses the DMN check); `reduce_predicate_required` (a quantifier with no predicate); `reduce_output_unmapped`
  (`output_field` absent from the summary schema); `reduce_source_missing` (the `source` root is not a declared
  binding input); and `reduce_numeric_type` (a numeric op whose `item_path` is declared non-numeric —
  best-effort, no false positives).

- **Gateways branch on strings.** `expr.py` compares string literals only (unchanged — a non-goal to widen).
  So the **gateway-facing** reduce ops are the string-valued `first` / `last` (with an `item_path` selecting a
  string field); `any`/`all`/`none` (bool), `count`/numeric feed capabilities, HITL, or further reducers. The
  seed's "is any party a hit?" therefore reduces with `first` (item_path `verdict`, predicate `= "hit"`) →
  `matched` = the hit verdict or `null`, which the gateway routes on.

- **Seed.** `wire-repair-screening`: a multi-instance `serviceTask` screens each party (a list of
  `party_result`s) → a `reduce` collapses it to a `summary` → an exclusive gateway routes on `summary.matched`.
  The canonical MI → reduce → gateway flow, end to end.

## Consequences

- A process can now route on an aggregate ("any/all/none/count over a list") via a pinned, validated capability
  reusing the existing IO machinery and the one bounded predicate surface — no new registry, no BPMN construct,
  no wider expression language. It closes the loop from "screen each party" to "route on whether any party is a
  hit."

## Non-goals

- Not a general collection-query language — no grouping, joins, multi-key sorting, chained reductions. No new
  BPMN construct (a capability on a `serviceTask`). No DMN `COLLECT` aggregators (that stays deferred; this is
  the standalone reducer). No widening of `expr.py` or the DMN unary surface. No wizard UI.
