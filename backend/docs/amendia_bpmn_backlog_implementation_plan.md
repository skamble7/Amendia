# Amendia — Deferred Backlog: Implementation Plan

**Purpose:** sequence and design-sketch the deferred backlog into a build plan. Companion to
`amendia_bpmn_deferred_backlog.md` (the *what/why-deferred*); this is the *how/when/in-what-order*, grounded in
the current code (platform through ADR-034 / Common Executable, verified 2026-07-17). Each item becomes its own
Claude Code prompt when we build it (same rhythm as the ladder); this plan is the map + the decisions to make
first.

## Progress (updated 2026-07-18)

**Waves 1 & 2 complete.** Shipped, each with its ADR + doc updates:

- **A** · real `llm`/`mcp`/`deep_agent` business-error mapping — **ADR-035**
- **B** · multi-instance activities (parallel + sequential, configurable list/indexed aggregation) — **ADR-036**
- **C** · native DMN (`decision` capability kind, scoped evaluator, bounded FEEL + hit policies) — **ADR-037**
- **R** · collection-reduction / summary (`reduce` capability kind — closes the "any/all over a list" gap) — **ADR-038**
- **D** · call activity / cross-pack composition (inline-compile, pin+splice+scope+IO-map, cycle/depth guards) — **ADR-039**

**Wave 3 in progress.** The cancellation / scope-interruption **foundation** shipped — cooperative cancellation
primitive proven by an interrupting timer boundary on a running `read_only` serviceTask (**ADR-040**). Now
building its consumers:

- **E** · interrupting boundaries on a `subProcess` (scope-level cancellation — extends the ADR-040 primitive
  to a whole scope; + error-boundary-on-scope routing) — **ADR-041** (shipped)
- **F** · event sub-process (interrupting error + timer handlers, process-level or scoped — reuses E's scope
  machinery with the ESP body as the inline handler; non-interrupting + message/signal-triggered deferred) —
  **ADR-042** (shipped)
- **G** · compensation **core** — explicit compensate-throw + `isForCompensation` handlers (bound undo
  capabilities) + a reverse-order compensation log with a no-double-undo re-entrancy guarantee (one activity
  per superstep → LangGraph's single-interrupt-per-node guarantee); transaction/auto-cancel/targeted/MI
  deferred — **ADR-043** (shipped). The heaviest item.

**BACKLOG COMPLETE (2026-07-18).** All nine items shipped — Waves 1–3 (A/B/C/R/D) + the cancellation foundation
+ its consumers (E/F/G) — ADR-035 through ADR-043. What remains are the *stretches* recorded as each item
shipped (below), not core constructs.

### Deferred stretches recorded across the arc (the remaining backlog)
- **B:** MI-on-subprocess, nested MI.
- **C:** DMN `COLLECT` aggregators; DMN authoring **wizard UI**; full FEEL.
- **R / gateways:** a small bounded `expr.py` extension so boolean/numeric (not just string) gateway branching
  is possible.
- **D:** nested-instance call-activity execution; call-a-pack-N-times (MI callee); boundary-on-callActivity;
  cross-pack role namespacing; dynamic callee.
- **E/F:** non-interrupting boundaries/ESPs (concurrent handler); message/signal/escalation-triggered
  boundaries + ESPs (scope-duration subscriptions); nested ESPs.
- **G:** transaction/cancel auto-compensation; targeted (`activityRef`) compensation; MI/nested/error-triggered
  compensation; capability-native inline `compensate` op; a batch compensation-authorization gate.

**Uncommitted:** the whole A→G arc (ADR-035–043, ~90 files) is uncommitted on `feat/deferred_backlog` as of
2026-07-18 — commit before a stray reset/checkout can lose it.

Newly recorded deferrals as items shipped: MI-on-subprocess / nested MI (B); DMN COLLECT aggregators + wizard
authoring UI (C); nested-instance execution / MI-callee / callActivity-boundary (D); a small bounded `expr.py`
extension so boolean/numeric gateway branching is possible (noted at R).

## How the plan is organized

Items are grouped into **waves** by dependency, ROI, and risk — not by backlog number. Two structural facts
drive the ordering:

- **A shared "cancellation / scope-interruption" substrate** is the real cost behind three items (interrupting
  boundaries, event sub-process, and — partly — compensation). Build it **once**, as a foundation, before
  those items rather than three times.
- **The execution-profile model is now two levels** (`common_subset`, `common_executable`). Every *new
  executable construct* simply becomes part of `common_executable`, and its `bpmn_*_unsupported` refusal code
  is retired as it ships. No new profile scaffolding is needed per item (unlike the ladder's granular levels).

## Dependency map

```
Wave 1 (no new substrate)         A real-error-mapping      B multi-instance ──uses── parallel Send (built)
Wave 2 (authoring/composition)    C native DMN              D call activity (cross-pack composition)
Wave 3 (interruption substrate)   ┌─ FOUNDATION: cooperative cancellation / scope interrupt ─┐
                                  │   E interrupting boundaries   F event sub-process          │
                                  └─────────── G compensation (also needs undo-capabilities) ──┘
Wave 4 (eventing breadth, niche)  H signals · escalation · timeCycle · richer correlation
Parallel strategic track          I LLM-agent execution mode  (independent of the compiler; go/no-go first)
Excluded (settled, not backlog)   concurrent human gates · inline scriptTask code
```

---

## Wave 1 — quick wins, no new substrate

### A · Real `llm`/`mcp` business-error mapping  ·  effort **S** · risk **L**
**Scope:** let a *real* (non-simulation) capability signal a modeled business error so error boundaries
(ADR-030) fire on real `llm`/`mcp`/`deep_agent` execution — not only on the sim path.
**Current seam (grounded):** `executor/core.py::_call` already catches `CapabilityBusinessError` and
re-raises it (vs wrapping other exceptions as `CapabilityError`), and the task runner routes it to
`state.boundary[element] = {"kind":"error","code":C}`. **But `_execute_llm_real` / `_execute_mcp_real` /
`_execute_deep_agent` never *raise* it** — they only return `{"outputs": …}`. This item wires the real
paths to detect a modeled-error signal and raise `CapabilityBusinessError(code)`.
**Key decision (settle before the prompt):** the signaling convention — for **MCP**, the `CallToolResult.isError`
flag and/or a structured `{error_code}` in the tool result; for **LLM**, a structured-output convention (a
discriminated `{business_error:{code}}` vs the normal output). Likely: MCP → `isError` + a conventional
`error_code` field; LLM → an optional error branch in the declared output contract.
**Deps:** none. **Why first:** smallest, and it's what makes the shipped error-boundary/message paths usable in
production rather than sim-only.

### B · Multi-instance activities (parallel + sequential)  ·  effort **M** · risk **M**
**Scope:** run a task (and later a sub-process) N times over a collection — "screen each party," "for each
attachment." Parallel and sequential (`isSequential`) markers.
**Current seam (grounded):** the **parallel fan-out already exists** (compiler maps `parallelGateway` → `Send`
fan-out; `state.py` reducers `artifacts`/`actor_log` are merge-safe). Parallel MI reuses that machinery.
**The one real design point:** with `artifacts` as a single `merge_dicts` channel keyed by binding name,
N concurrent iterations writing the same output name would **clobber (last-wins)** — so MI needs **per-iteration
artifact scoping** (indexed keys) and an **aggregation rule** (collect into a list artifact on join). Sequential
MI is a loop with a cardinality/collection guard.
**Key decisions:** the aggregation shape (list artifact vs indexed map); completion condition
(all vs `completionCondition`). **Deps:** parallel (built). **Why second:** high payments value, and the
parallel substrate makes it much cheaper than it looks.

---

## Wave 2 — authoring & composition

### C · Native DMN evaluation (`businessRuleTask`)  ·  effort **M–L** · risk **M**
**Scope:** evaluate a DMN decision table (FEEL, hit policies) natively, instead of routing a
`businessRuleTask` to a bound capability (today's behavior; `decisionRef` is captured for inference only,
ADR-033).
**Design fork (decide before the prompt): build vs adopt.** *Adopt* a Python DMN/FEEL library (fast coverage,
a new dependency, FEEL semantics you don't own) vs *build* a scoped decision-table evaluator (own it, bounded
FEEL). Either way: a new capability kind (`decision`/`dmn`) or a decision-executor, `decisionRef` resolution,
decision versioning/pinning, and a verdict artifact validated like any output.
**Deps:** none hard; complements task-kinds. **Value:** business users author rules as auditable tables (no
code) — a natural payments fit.

### D · Call activity / cross-pack composition  ·  effort **L** · risk **M–H**
**Scope:** a `callActivity` invoking another *pack* as a reusable sub-process (today refused,
`bpmn_call_activity_unsupported`).
**Why it's big:** it's a **contract + resolver** problem, not a compiler tweak — which `pack_key@version` is
called, **IO mapping** between caller state and callee inputs/outputs, **pinning the callee** at activation for
reproducibility (extend the resolution sidecar), recursion/cycle guards, and audit across the boundary. Two
execution options: **inline-compile** the callee like an embedded sub-process (reuses the 2.6 flatten model —
simplest) or a **nested instance** (truer isolation, heavier).
**Key decisions:** inline vs nested; how the callee is pinned; the IO-mapping contract shape. **Deps:** cleanest
after sub-process (built). **Value:** reuse at scale once many packs share procedure.

---

## Wave 3 — the interruption substrate + what it unlocks

### FOUNDATION · Cooperative cancellation / scope interruption  ·  effort **M–L** · risk **H**
**Why a foundation:** the timer/error rungs only handled cases that **don't** need to interrupt in-flight work
(a parked HITL gate; a synchronous serviceTask error). The next boundary/event items need to **cancel a
running capability or a whole scope**. Build this once: cooperative cancellation of a running node/capability
(a cancellation token honored by the executor), LangGraph interruption of a running superstep, and
**scope-level propagation** (cancel every node inside a sub-process). This is the highest-risk item in the
backlog — it touches the executor, the engine's run loop, and checkpoint/recovery semantics.
**Decision:** build it as an explicit foundation phase, or fold a minimal version into E. Recommend explicit
foundation — E, F, and G all lean on it.

### E · Interrupting boundaries on running work  ·  effort **M** (given the foundation) · risk **M**
**Scope:** timer boundary on a `serviceTask` (SLA on an agent task) and boundary events on a `subProcess`
(both refused today: `bpmn_timer_boundary_host_unsupported`, `bpmn_subprocess_boundary_unsupported`).
**Seam:** reuses the existing `boundary` state channel + router; the *new* part is cancelling the running host
(the foundation). **Deps:** the cancellation foundation.

### F · Event sub-process  ·  effort **M** · risk **M**
**Scope:** an event-triggered handler inside a scope (interrupting or non-interrupting). **Deps:** the
cancellation foundation (interrupting variant) + the message/timer substrates (built). Niche but a natural
follow-on once cancellation exists.

### G · Compensation / transaction sub-process  ·  effort **L (heaviest)** · risk **H**
**Scope:** undo completed side-effects on later failure (compensation handlers, compensate throw/boundary,
transaction scope). **Why last:** BPMN's hardest corner (reverse-order execution, pairing activities with
compensators) **and** it's meaningful only if side-effectful capabilities expose real **undo** operations — so
it needs a capability-contract extension (a `compensate` operation) plus a per-instance compensation log.
**Deps:** scope semantics from the foundation; undo-capable capabilities.

---

## Wave 4 — eventing breadth (niche / opportunistic)

### H · Signals, escalation, `timeCycle`, richer correlation  ·  effort **S–M each** · risk **L–M**
Each is a small extension of an existing substrate: **signal events** (1-to-many broadcast — extend the message
intake/fan-out), **escalation events** (non-interrupting up-hierarchy), **`timeCycle`/recurring timers** (extend
the timer poller), **richer correlation properties** (beyond the business-anchor). Do opportunistically when a
concrete process needs one — not as a block. Message/timer **start** events remain N/A (instances start from
exception dispatch).

---

## Parallel strategic track

### I · LLM-agent execution mode  ·  effort **L** · risk **H (strategy)** · **decide go/no-go first**
**Not a BPMN construct** — a *second execution style* for ill-structured exceptions you can't diagram: an LLM
agent reasons over MCP tools + a goal, choosing steps at runtime, with HITL gates, **no fixed BPMN graph**.
Reuses the HITL/audit/artifact/SoD substrate; **does not touch the BPMN compiler**, so it can proceed in
parallel with the waves above. Its trade is flexibility for reproducibility (you can't pin an LLM's routing).
**This needs its own ADR + a go/no-go decision before planning** — it's a product bet, not a construct. Amendia
already seeds it (the `deep_agent` capability kind, `executor/deep_agent.py`), but as a *within-node* loop, not
an orchestrator. Recommend a short **design spike/ADR** to decide scope before committing.

---

## Cross-cutting notes

- **Profiles:** each new executable construct joins `common_executable` and retires its `*_unsupported` code;
  update `compilability.py`, the coverage classifier, and the onboarding guide's element matrix as each ships.
- **Docs discipline (as established):** every item ends with an ADR (ADR-035+), updates
  `amendia_process_onboarding_guide.md` (§11 codes, §12 matrix), and strikes its line in the backlog doc.
- **Each item's prompt begins with a targeted recon** (like the ladder rungs) — this plan is the design sketch,
  not the final seam list.

## Decisions to settle before we start

1. **Sequence** — confirm the wave order (recommended: A → B, then C/D, then the cancellation foundation → E/F →
   G; H opportunistic; I as a parallel track).
2. **Item A signaling convention** — MCP `isError`/`error_code` + LLM structured-error branch (settle when we
   write A's prompt).
3. **Item C — DMN build vs adopt.**
4. **Item I — is the LLM-agent mode in scope for this push** (parallel track now), or parked behind its own ADR
   for later?
5. **Wave 3 — build cancellation as an explicit foundation** (recommended) vs fold into E.

## Recommended immediate next step

**Wave 1, Item A** (real business-error mapping) — smallest, no new substrate, and it turns the shipped
error-boundary/message paths from sim-only into production-usable. I'll settle the signaling convention and
write its Claude Code prompt on your go.

---

*Living doc: reorder as priorities shift; when an item ships, move it out of the plan, cite its ADR, and strike
it in `amendia_bpmn_deferred_backlog.md`.*
