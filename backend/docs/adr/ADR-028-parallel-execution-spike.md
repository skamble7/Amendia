# ADR-028 — Parallel-gateway execution spike: extend-native holds (Common Executable go/no-go)

- **Status:** Accepted
- **Date:** 2026-07-17
- **Related:** **ADR-027** (BPMN conformance — Phase 2 is this spike; §4–5 locked the two decisions), **ADR-011** (native LangGraph execution — the model this extends), **ADR-019** (memoization — the Phase 2.0 hazard closed here), `backend/docs/amendia_bpmn_conformance_dossier.md` §6, `libs/amendia_bpmn/compilability.py`, `agent-runtime/app/engine/{compiler,engine}.py`.
- **Decision:** **Proceed with extend-native** for the Common Executable ladder. Embed-SpiffWorkflow is **not** needed — the two costs the dossier isolated (concurrent-HITL representability, checkpoint/audit re-homing) are both resolved natively.

## Context

ADR-027 Phase 2 asks: can the native LangGraph engine grow toward the BPMN *Common Executable*
conformance sub-class, or must we embed an external BPMN engine? Two product decisions were locked
first (ADR-027 §4–5): **(a) sequentializing the fan-out is acceptable** — no two human gates need be
open at once, so the one-`WAITING_HITL`-per-instance model stays; **(b) native-default memoization
flips on** (Phase 2.0). The dossier isolated the real fork as *not* gateway syntax but two costs:
**concurrent-HITL representability** and **audit/checkpoint re-homing**. This spike lands `parallelGateway`
fork/join behind a flag and answers the go/no-go empirically.

## Findings

### 1. Native memoization default (Phase 2.0) — hazard closed

`AGENTRT_MEMOIZE_CAPABILITIES` now defaults **true**, and `build_executor` defaults a process-local
memo store when none is injected (`main.py` still injects the durable Mongo store). LangGraph replays
the interrupted node from the top on resume; without a memo a non-deterministic capability above a
gate would re-invoke and commit an artifact the human never reviewed. Proven with a **non-deterministic**
fake capability (`test_memoization.py`): on approve/resume the reviewed artifact commits (no re-invoke);
on reject the capability genuinely re-runs (fresh `attempt`). Simulation suites unchanged (deterministic
→ memo is observationally transparent). Set the flag false for byte-identical replay.

### 2. Fork/join executes natively — **the native model holds**

The compiler maps a `parallelGateway` to a **passthrough node** (ADR-027 Phase 2.1): a fork's N outgoing
edges fan out (LangGraph runs the successors in one superstep), a join's N incoming edges are a barrier
(LangGraph runs it once all branches complete). The **tailwind held**: `ProcessState`'s existing reducers
— `artifacts` dict-merge and `actor_log` append (`state.py:23-24`) — merge concurrent branch writes with
no lost updates and **no new channel design**. Verified end-to-end on the wire-repair notify+record
fan-out (the exact case the executable projection had to linearize): it compiles under the `parallel`
profile, both branches' artifacts + actor-log entries land, outcome is deterministic
(`test_parallel_spike.py`).

### 3. Concurrent HITL — sequentialized via **id-keyed resume** (the crux)

Empirically (LangGraph 0.4.6): when two parallel branches each call `interrupt()` in the same superstep,
**both interrupts surface at once** (`result["__interrupt__"]` has 2). A **bare** `Command(resume=value)`
then *raises* — "When there are multiple pending interrupts, you must specify the interrupt id." The
mechanism that makes sequentialization work:

- each `Interrupt` carries a stable `.id`;
- `Command(resume={id: value})` resolves **exactly one** interrupt — the other stays pending;
- re-invoking surfaces the next pending interrupt.

So the engine now: surfaces `interrupts[0]`, materializes **one** `HitlTask` carrying its `interrupt_id`
(new field on the `HitlTask` contract, additive-optional), parks at `WAITING_HITL`; on that decision's
resume it builds `Command(resume={interrupt_id: decision})`; the next interrupt then surfaces — **one open
HITL task per instance at all times**. The id-keyed form also works for a lone interrupt, so the single-gate
path is unified (all existing HITL tests stay green). SoD (`compute_sod_excluded`) and claim/decide are
per-task and carried over unchanged. Proven: two concurrent gates resolve one-at-a-time, both branch
artifacts commit (`test_parallel_spike.py::test_mechanism_two_concurrent_gates_serialize_via_id_keyed_resume`).

### 4. Checkpoint + recovery across a fork — no re-homing needed

The Mongo checkpointer persists the parallel frontier as ordinary channel state keyed by `thread_id`;
`engine.recover()` re-invokes a mid-fan-out instance with `None`, which restores from the last checkpoint
and re-surfaces the pending gate. The audit story (the checkpoint trail, `state.py:5`) and crash recovery
(`engine.py:194-204`) are **unchanged** — the second dossier cost (re-homing durable state onto an
external engine's task tree) simply does not arise. Verified with a re-invoke-`None`-mid-fork test.

### 5. Profile consistency — a **deployment-level** flag, coupling flagged

Which constructs are executable is one source of truth — `compilability_findings(model, *, profile)` in
`amendia_bpmn` — consulted by **both** the registry activation gate (`PackValidator` Stage 1) and the
runtime compiler (`compile_graph`), so they can never disagree. The coverage classifier (`parse(...,
profile=)`) likewise promotes `parallelGateway` `documented → executable` under the profile. Flags:
`AGENTRT_EXECUTION_PROFILE` (runtime) and `REGISTRY_EXECUTION_PROFILE` (registry), both default
`common_subset` (Phase-0/1 behavior — parallel still refused).

**The coupling, stated plainly (do not hand-wave):** a pack activated under the `parallel` profile carries
no per-pack record of that fact today; it will fail to **load** at runtime if that runtime is on
`common_subset`. For the spike this is a **deployment-level** invariant — *the registry and the runtime
must run the same `EXECUTION_PROFILE`*. Promoting parallel to the default (or mixing profiles across a
fleet) needs the profile carried **on the pack** (e.g. an additive `manifest`/sidecar `execution_profile`
pin, validated at load) so a runtime refuses a pack it can't run with a clear error rather than a
compile-time surprise. That pinning is deferred to the ladder work, not the spike.

## Limitations recorded (spike scope)

- **Structured, non-nested fork/join only.** The compiler wires each parallel gateway's outgoing edges
  directly; it does not validate fork↔join *pairing* or handle **nested** parallel scopes. A malformed or
  nested parallel structure may produce a graph that dead-locks the join barrier. The ladder work should
  add pairing validation (and a `bpmn_unbalanced_parallel` finding) before promoting parallel to default.
- **No conditions on parallel flows** — already enforced by the parser (`bpmn_parallel_flow_condition`).
- **Sequentialized gates only** — by decision (ADR-027 §4). Concurrent human gates remain out of scope; the
  one-`WAITING_HITL` model is intact.
- **Profile is deployment-level** — see §5; per-pack pinning is deferred.

## Recommendation

**Extend-native. Do not embed SpiffWorkflow.** Both costs the dossier flagged dissolved: concurrent-HITL is
representable by *sequentializing* concurrent interrupts through id-keyed resume (§3), and the checkpoint/
audit substrate needs **no** re-homing (§4) — the existing reducers even gave concurrent-write merge for
free (§2). Embedding an external engine would have imposed a second execution model, a durable-state
migration, and a reconciled audit story for zero incremental capability the native path can't reach.

The Common Executable ladder (ADR-027 §2.2+) proceeds native, one construct per prompt, each following the
same shape this spike validated — *promote the tier `documented → executable` under the profile, teach the
compiler, extend coverage + the compilability predicate, add tests*: event-based gateway + intermediate
catch (await/timeout) → boundary events (SLA/escalation timer, rejection/compensation error) → sub-process
/ call activity → send/receive/script/businessRule (DMN) tasks.

> **Rung 1 landed — timers (ADR-029).** Timer intermediate-catch + interrupting SLA boundary on a HITL
> gate, behind a new cumulative `timers` profile, on a native durable-timer substrate (Mongo `timers` +
> lifespan poller + injectable clock). `due_at` now fires; the reference approve-gate SLA → escalation
> path runs end to end. Boundary-on-serviceTask and `timeCycle` are deferred (see ADR-029). Before parallel (or any construct) becomes
the **default** profile, land the two deferred items: **per-pack profile pinning** (§5) and **fork/join
pairing + nested-scope validation** (Limitations).

## Consequences

- Parallel gateways run end-to-end behind `EXECUTION_PROFILE=parallel` (default off — Phase-0/1 behavior
  preserved: parallel still refused at activation and compile under `common_subset`).
- The native engine is the funded path toward Common Executable; execution grows incrementally and
  spec-anchored rather than via an open-ended external-engine migration.
- `HitlTask` gains `interrupt_id` (additive-optional); the engine resumes by interrupt id (unifying single
  and concurrent gates). No behavior change on the default profile.

## Resolved — Phase 2.5 (per-pack pinning + fork/join validation)

The two deferred items this spike flagged as blockers before parallel can become the default profile are
now **closed** (ADR-027 Phase 2.5); the profile model lives once in `amendia_bpmn` and is shared by both
services:

- **Per-pack profile pinning (§5 → resolved).** `required_profile(bpmn_model)` is *derived* from the BPMN
  at activation (`parallel` iff the diagram has parallel gateways, else `common_subset`) and pinned into
  the **resolution sidecar** — `Resolution.required_execution_profile`, a derived pin, *not* the immutable
  manifest (no `manifest_version` bump), immutable once active and exposed on
  `GET /packs/{k}/{v}/resolution`. Because it is derived, it can't drift from the diagram. The runtime
  refuses a pack at **load** (not mid-flight) when `profile_rank(required) > profile_rank(EXECUTION_PROFILE)`,
  raising `PackRequiresProfile` → a distinct `pack_requires_profile` dispatch-rejection reason (not a
  generic `unknown_pack`/compiler error). Profiles are a **hierarchy checked with `>=`**: a `parallel`
  runtime runs `common_subset` packs; a missing pin (older packs) defaults to `common_subset`.
- **Fork/join pairing + nested-scope validation (Limitations → resolved).** `compilability_findings(model,
  *, profile="parallel")` now runs structural validation: balanced (fork count == join count, no degenerate
  1-in-1-out), block-structured (each fork's branches converge on one join), and **nested parallel
  rejected** — surfaced as error-severity `bpmn_parallel_unbalanced` / `bpmn_parallel_unstructured` /
  `bpmn_parallel_nested_unsupported` findings at the same registry activation gate and runtime compile gate.

The default stays intentionally conservative (`EXECUTION_PROFILE=common_subset` in both services); parallel
remains opt-in. Promoting it to the default is now a config change, not a code gap — the safety rails
(derived pin + load-time `>=` guard + structural validation) are in place.
