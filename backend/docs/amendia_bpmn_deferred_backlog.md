# Amendia — BPMN Execution: Deferred Backlog

**Purpose:** a living backlog of everything deliberately deferred while building the BPMN Common-Executable
ladder (ADR-027 → ADR-034). Each item was a *scoped decision*, not an oversight — recorded here with why it
was deferred, what building it takes, its value in the payments-exception context, and the ADR where the
decision lives.

**Status of the program:** the Common-Executable construct set is complete — `common_subset → parallel →
timers → error_boundary → messages → subprocess → tasks`, consolidated to two conformance levels
(`common_subset`, `common_executable`) with the default flipped to `common_executable` (ADR-034). Amendia
*ingests* Full BPMN (classify-don't-reject + inference) and *executes* Common Executable. Everything below is
beyond that line.

---

## 1. Cross-process composition — `callActivity` — ~~SHIPPED (ADR-039)~~
**Shipped in:** ADR-039 (Backlog #1). A `callActivity` binds a **`call` executor** referencing another pack
(`calledElement` = pack_key + `amendia:calledVersion` range); the callee is **pinned to an exact `pack@version`
at activation** (`resolution.call_activities`; refused if not active) and **inline-compiled** into the caller's
graph — every callee node id / artifact key scoped by the callActivity id, with an explicit `input_map`
(caller state → callee inputs) / `output_map` (callee outputs → caller state). **One** instance, **one**
checkpoint, **one** audit trail. Acyclic bounded-depth call graphs run (nested A→B→C flattens); cycles
(`bpmn_call_activity_cycle`), excess depth (`bpmn_call_activity_depth`), no-target, unresolved callee
(`call_activity_pack_unresolved`), unmapped/mismatched IO (`call_activity_io_unmapped`/`_io_mismatch`) are
refused. The composite required profile is `max(caller, callee)`. `bpmn_call_activity_unsupported` is retired
(now the common_subset profile-gate code).

**Still deferred (new stretches, from ADR-039):** **nested-instance execution** (a child instance + parent↔child
correlation + isolation — inline-compile is this cut); **callActivity as a multi-instance host**
(`bpmn_call_activity_multi_instance_unsupported`, call-a-pack-N-times); **boundary events on a callActivity**
(reused subprocess-boundary refusal); cross-pack **role namespacing** beyond reuse-as-is; and **dynamic**
(runtime-chosen) callees (the pin is fixed at activation).

## 2. Native DMN — `businessRuleTask` decision tables — ~~SHIPPED (ADR-037)~~
**Shipped in:** ADR-037 (Wave 2). A `businessRuleTask` now binds a `kind: decision` capability whose runtime
carries an **inline decision table** (pinned like any capability — no separate DMN registry). A scoped,
build-not-adopt evaluator (`amendia_bpmn.dmn`, shared by the registry validator + runtime) covers a bounded
FEEL unary-test surface + `UNIQUE/FIRST/PRIORITY/ANY/COLLECT` hit policies, emitting a schema-validated verdict
artifact downstream gateways consume. Malformed tables / unresolved mappings are refused at validation
(`dmn_table_malformed`, `dmn_unknown_hit_policy`, `dmn_bad_unary_test`, `dmn_input_unresolved`,
`dmn_output_unmapped`, `dmn_rules_overlap`); a `UNIQUE`/`ANY` violation at runtime is a technical failure (not
a boundary route). Native DMN is opt-in — a `businessRuleTask` bound to a plain capability is unchanged.

**Still deferred (from ADR-037):** the DMN **authoring wizard UI** (form-based table authoring in onboarding);
**COLLECT aggregators** (sum/min/max/count — list-only for now); and **full FEEL** (functions/arithmetic/
contexts/BKMs — deliberately outside the bounded surface).

## 3. Multi-instance activities — ~~SHIPPED (ADR-036)~~
**Shipped in:** ADR-036 (Backlog #3). A `multiInstanceLoopCharacteristics` on a **task** now runs N times —
**parallel** (the ADR-028 `Send` fan-out → a join barrier) and **sequential** (`isSequential`, a guarded loop
with `completionCondition` early-exit) — over a `loopCardinality` or a `loopDataInputRef` collection. Each
iteration writes an index-scoped `mi_results["{host}/{i}"]` key (never the bare binding, so parallel writes
never clobber); the join aggregates in **index order** into a list artifact (default) or `amendia:aggregation="indexed"`
`{binding}#i` keys, validated against the pinned schema. MI activates only under `common_executable`.

**Still deferred (new stretch, from ADR-036):** **MI on an embedded sub-process** (refused with
`bpmn_multi_instance_subprocess_unsupported`) and **nested MI** (`bpmn_multi_instance_nested_unsupported`) —
MI-on-subprocess compounds with the ADR-032 inline-flatten (per-instance nested-scope isolation) and is a
larger design. Also deferred this cut: **HITL-gated MI** (iterations run autonomously; refused at compile) and
**parallel early-cancel** via `completionCondition` (honored for sequential only).

## 4. Compensation / transaction sub-process — ~~core compensation SHIPPED (ADR-043)~~
**Shipped in:** ADR-043 (Backlog #4, Item G — the last & heaviest item). A **bounded core cut**: a compensable
side-effectful `serviceTask` with a compensation `boundaryEvent` (+ `<association>`) paired to an
`isForCompensation` **undo handler**, and an **explicit compensate throw** event that undoes the scope's
completed compensable activities in **reverse (LIFO) order** — each through its HITL gate, exactly once. The
mechanism: an append-only per-instance **`compensation_log`** (entry on each compensable commit) + a companion
`compensations_done` channel; the throw compiles to a **self-looping driver** that compensates one activity per
superstep (so LangGraph's single-interrupt-per-node guarantee makes each undo run exactly once — the
**re-entrancy / no-double-undo** property survives an HITL-resume replay or a crash recovery). The off-flow
handler is inlined (like an ESP body). Read-only primaries, unbound handlers, and the deferred variants are
refused (`bpmn_compensation_handler_not_side_effect`, `_handler_unbound`, `_transaction_unsupported`,
`_targeted_unsupported`, `_multi_instance_unsupported`; a throw with nothing to compensate warns
`bpmn_compensate_throw_no_handlers`). The `payment-compensation` seed runs both paths.

**Still deferred (new stretches, from ADR-043):** the **transaction sub-process** + **cancel end event**
(automatic compensation on transaction cancel — the throw here is *explicit*); **targeted** compensation
(`activityRef` → one activity — this cut is scope-wide); compensation of **multi-instance / looped** activities,
**nested** compensation, and **error-boundary-triggered** automatic compensation; a **capability-native
`compensate` operation** (inline undo on the descriptor vs a separate handler activity); and a
**compensation-authorization batch gate** (approve all undos at once vs per-handler).

## 5. Interrupting boundaries on running work — ~~single-node + scope-level cancellation + event sub-process SHIPPED (ADR-040/041/042)~~
**Shipped in:** ADR-040 (single-node) + ADR-041 (scope-level) + ADR-042 (event sub-process, Item F). An
interrupting **timer boundary on a running `serviceTask`** (ADR-040) and on a **`subProcess`** (ADR-041) now
self-enforce an **in-process SLA deadline** via a cooperative `CancellationToken` + injected clock. For a
subProcess the deadline is stamped at scope entry and projected onto every inner node (`min(own,
remaining-scope)`); a breach by any inner node marks `boundary[scope_id]` and diverts the whole scope to the
handler, committing nothing, re-entrant. An **error boundary on a subProcess** (ADR-041) is a routing fallback —
an inner node's uncaught modeled error routes to the enclosing scope's handler (nested inner→outer) before
`FAILURE_SINK`. **Item F / ADR-042** adds the **event sub-process** (`triggeredByEvent="true"`): an interrupting
**error** or **timer** start makes the ESP a scope-wide handler triggerable from *anywhere* in its enclosing
scope — and that scope may be the **whole process** (which a subProcess boundary can't express) as well as a
nested subProcess. It reuses ADR-041's machinery — the handler is registered as a boundary on the enclosing
scope (generalized to `process_id`) and the ESP **body is inlined** as the handler; inner-most matching handler
wins (own boundary > subProcess ESP > process ESP). `bpmn_timer_boundary_host_unsupported` and
`bpmn_subprocess_boundary_unsupported` are retired for these cases; a side-effectful/HITL task in an
interrupting-timer scope (subProcess *or* whole process) is refused
(`bpmn_timer_boundary_side_effect_unsupported`, `bpmn_subprocess_boundary_side_effect_unsupported`,
`bpmn_subprocess_timer_scope_hitl_unsupported`).

**Honest limitation + still deferred:** LangGraph nodes are atomic supersteps, so this is **cooperative
self-cancellation** — interruption is between inner nodes + node-self-enforced, never mid-node by external
preemption; **external/asynchronous preemption** is out of scope. **Still deferred (new stretches, from
ADR-042):** **non-interrupting** event sub-processes (a concurrent handler that doesn't cancel the scope);
**message/signal/escalation-triggered** ESPs (need a scope-duration subscription, like the deferred
message/signal boundaries); **nested** ESPs and an **ESP carrying its own boundary**; and ESP **self-retrigger**
(all refused today via `bpmn_event_subprocess_unsupported` / `bpmn_event_subprocess_ambiguous`). Also remaining:
**interrupting a side-effectful / running task with undo** and side-effectful/HITL scopes → **Item G**
(compensation, see #4); *message/signal/escalation* boundaries on a subProcess stay deferred.

## 6. Eventing breadth
**Deferred in:** ADR-029 (`timeCycle`/recurring timers, timer start events) and ADR-031 (signal & escalation
events, message start events, full correlation properties/expressions).

Niche extensions of substrates already built: **signal events** (1-to-many broadcast vs message 1-to-1),
**escalation events** (non-interrupting, up a hierarchy), **`timeCycle`/recurring timers**, **message/timer
start events** (a different instantiation model — Amendia instances start from exception dispatch, so mostly
N/A), and **richer correlation** (vs the business-anchor matching shipped). **Value:** mostly low/niche;
signals (fan-out) and multi-key correlation are the most likely to matter.

## 7. Deliberate policy choices (settled boundaries, not really backlog)
- **Concurrent human gates** — sequentialized *by decision* (ADR-027 §4 / ADR-028). Revisit only if a use case
  needs two independent approvals open at once; it would reopen the one-`WAITING_HITL`-per-instance model.
- **Inline `scriptTask` code** — refused *by design* (ADR-033); arbitrary code fights the capability/audit
  model. The intended answer is "bind a skill capability," not "add a script engine." Settled, not deferred.

## 8. Capability-execution maturity (adjacent to BPMN)
**Deferred in:** ADR-030 (real business-error mapping), ADR-031 (typed message-payload transforms).

- ~~**Real `llm`/`mcp` business-error mapping**~~ — **SHIPPED (ADR-035).** A real MCP tool's
  `result.isError` + `error_code`, and a real `llm`/`deep_agent` `{"business_error": {...}}` object, now each
  raise `CapabilityBusinessError`, routed to the BPMN error boundary exactly as the sim path is (ADR-030).
  The element's legal boundary codes are threaded to the LLM prompt via the additive
  `ExecutionContext.extras["error_codes"]` key; the MCP Implementor Guideline (§4a) documents the signalling
  convention.
- **Typed message-payload transforms** — beyond the validate-and-commit shipped in ADR-031.
- ~~**Collection-reduction / summary capability**~~ — **SHIPPED (ADR-038).** A `reduce` capability kind
  collapses a **list** input artifact into a scalar/summary output a gateway can branch on — quantifiers
  (`any`/`all`/`none`), `count`, numeric (`sum`/`min`/`max`/`avg`), positional (`first`/`last`) — over the
  **reused DMN bounded predicate surface** (`amendia_bpmn.reduce`, shared by registry + runtime). Binds an
  ordinary `serviceTask` (no BPMN/compiler change); pinned + validated like any capability (`reduce_*` codes);
  a runtime misfire is a technical failure, not a boundary route. Closes the loop from "screen each party" to
  "route on whether any party is a hit" — the `wire-repair-screening` seed runs MI → reduce → gateway end to
  end. (`expr.py` and the DMN surface stay scalar/string by design; gateways branch on the string-valued
  `first`/`last` reduce outputs.)

## 9. Separate track — LLM-agent execution mode
**No ADR yet — proposed track** (discussed during the ladder; see the two-mode reflection).

Not a BPMN construct: a `deep_agent`-style *unstructured* orchestration for ill-structured exceptions you
can't cleanly diagram. Reuses the HITL/audit/artifact/SoD substrate; its own strategy decision (flexibility vs
reproducibility). The other half of "agentic," complementary to — not competing with — the BPMN engine.

---

## Suggested order if the work resumes

| Priority | Item | Why |
|---|---|---|
| ~~Quick win~~ ✅ | ~~Real llm/mcp business-error mapping (#8)~~ — **shipped, ADR-035** | Small; unblocked the error paths on *real* capabilities |
| ~~High ROI~~ ✅ | ~~Multi-instance, parallel (#3)~~ — **shipped, ADR-036** (parallel + sequential) | Cheap on the existing parallel substrate; real payments value |
| ~~Authoring~~ ✅ | ~~Native DMN (#2)~~ — **shipped, ADR-037** | Business-rule authoring without code |
| ~~Big bet~~ ✅ | ~~Call activity (#1)~~ — **shipped, ADR-039** (inline-compile) | Reuse at scale once there are many packs |
| Big bet | LLM-agent mode (#9) | Strategy fork; the other half of "agentic" |
| ~~Interrupting boundaries~~ ✅ | ~~Interrupting boundaries / scope cancellation / event sub-process (#5)~~ — **shipped, ADR-040/041/042** | Cooperative self-cancellation; the last Wave-3 construct (event sub-process) |
| ~~Compensation~~ ✅ | ~~Compensation (#4)~~ — **shipped, ADR-043** (explicit throw + reverse-order undo) | The heaviest item; reverse-order undo of committed side effects with no-double-undo re-entrancy |
| Heavy / rare | Eventing breadth (#6) | Niche |

*Settled (not backlog): concurrent human gates, inline scripts (#7).*

---

*Maintainers: when an item ships, strike it here and cite the new ADR; when a new deferral is made in a future
rung, add it with its ADR pointer. Keep this the single index of "what BPMN we chose not to execute yet."*
