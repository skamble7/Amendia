# ADR-040 — Cooperative cancellation: interrupting timer boundary on a running serviceTask

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-029 (timer substrate / idle-gate SLA — the
`boundary` channel + router this reuses), ADR-030 (boundary router), ADR-034 (profiles). **Backlog:** the
Wave-3 foundation for item **#5** (interrupting boundaries); the scope-cancel / event-subprocess /
side-effectful-interruption consumers (E/F/G) are explicit follow-ons.

## Context — the decisive architectural fact

LangGraph nodes are **atomic supersteps**: you cannot externally preempt a node that is already running.
There is no "fire a timer that reaches into a running node and stops it." The existing timer *boundary* only
resumes an **idle** HITL interrupt with `{"__timeout__": true}` (a parked, durable-timer SLA on a HITL gate);
it never interrupts running work — which is exactly why `bpmn_timer_boundary_host_unsupported` refused a
`serviceTask` host. This is the highest-risk backlog item (it touches the executor, the run loop, and
checkpoint/recovery), so we build a **foundation-only cut**: the cancellation primitive + one minimal proof.

## Decision

**Node self-enforced cancellation.** The buildable, honest model of "interrupting boundary on a running task"
is: the node knows its own boundary timer at entry, wraps its own capability execution in an **in-process
deadline**, and *chooses the boundary path* on breach. Cooperative self-cancellation, not external preemption.

1. **`CancellationToken` + in-process deadline.** A small `CancellationToken` (`set()`, `cancelled`, optional
   `deadline`) is threaded into `ExecutionContext.cancel` (additive, like ADR-035's `error_codes`; `None` on
   the ordinary path). When a host `serviceTask` carries a boundary timer, the node runs `_produce_outputs`
   (execute + validate; the retry loop shares the one budget) in a worker future and polls the **injected
   clock** against a deadline = the boundary timer's duration. On breach it `set()`s the token, stops waiting,
   and takes the boundary path.

2. **Executor honors the token (cooperative).** The real paths (`_execute_mcp_real` / `run_real_llm`) poll
   `cancel.cancelled` at their natural checkpoints (before a tool call / between LLM turns) and bail; the sim
   path ignores it (instant, deterministic). Nothing about the return shape changes — a cancelled call simply
   doesn't commit.

3. **All-or-nothing commit → clean checkpoint (the recovery-safety crux).** A cancelled node commits **no
   partial artifact** — only `boundary[host] = {"kind":"timer"}` is written, and the existing router (ADR-029/030)
   routes to the timer target. So the post-node checkpoint is clean and fully re-entrant (same discipline as
   HITL propose/execute re-run-from-top).

4. **Honest limitation — cooperative abandon.** Python can't force-kill the capability thread. On breach the
   result is **discarded** and the thread **abandoned** (`ThreadPoolExecutor.shutdown(wait=False)` — the graph
   never blocks on it); a well-behaved capability checks `token.cancelled` and returns early, a runaway thread
   leaks until it finishes but its output is ignored.

5. **In-process vs durable.** The running-task SLA is enforced **in-process** (a thread is live — no durable
   Mongo timer row), unlike the idle-park gate SLA which persists in `timers`. **On a crash mid-task,**
   LangGraph re-runs the node from the top on recovery and the in-process deadline **re-arms fresh** — the
   running-task clock restarts on re-execution; the parked-gate clock persists. Accepted semantic.

6. **Side-effect safety (scope guard).** Interrupting a **running side-effectful** capability is unsafe (the
   side effect may have partially executed — that's compensation, Item G). So this cut allows the interrupting
   timer boundary on a `serviceTask` **only for a `read_only`-bound, autonomous (hitl `none`) capability**. A
   side-effectful host is refused at pack validation (`bpmn_timer_boundary_side_effect_unsupported`); a
   non-autonomous host is refused at compile. `bpmn_timer_boundary_host_unsupported` is retired for the
   capability-host case (a message host stays refused); the sub-process-boundary refusal
   (`bpmn_subprocess_boundary_unsupported`) is untouched (→ E).

## Consequences

- A `serviceTask` bound to a read_only capability with a timer boundary self-enforces an in-process SLA
  deadline; on breach it commits nothing, marks the `boundary` channel, and routes to the timer target via the
  existing router — the instance stays running. The token is threaded to the real executor paths and honored;
  the checkpoint after cancellation is clean and re-entrant. The idle-gate SLA (userTask) and all non-boundary
  paths are byte-unchanged.

## Deferred / non-goals (the E/F/G follow-ons)

- **Scope-level cancellation** (cancel every node inside a sub-process) — the token/primitive is *built to
  extend*, but implemented in **E** (boundary events on a `subProcess`). This cut proves single-node
  cancellation only.
- **Event sub-process** → **F**. **Interrupting a side-effectful / running task with undo** → **G**
  (compensation).
- **External / asynchronous preemption** of an already-running node (a message/signal cancelling running work)
  — out of scope by the LangGraph-atomicity argument; the node only self-enforces a deadline known at entry.
- No change to the durable idle-gate timer, the message substrate, or `WAITING_TIMER`.
