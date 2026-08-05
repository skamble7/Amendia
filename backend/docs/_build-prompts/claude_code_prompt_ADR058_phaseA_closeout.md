# CC Prompt — ADR-058 Phase A closeout: full node-factory span coverage + real worker OTLP bootstrap

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md` and the Phase A prompt (`backend/docs/_build-prompts/claude_code_prompt_ADR058_phaseA_telemetry_foundation.md`). Phase A landed and is verified; this closeout finishes its two known edges so the "one coherent trace + lineage, in both modes" guarantee is **general**, not just true for the wire-repair happy path. Reuse the existing `amendia_telemetry` helpers and the agent-runtime helpers you already wrote (`node_span`, `link_to`, `current_traceparent`, `emit_linked_span`, and in `task_runner.py`: `_node_span_attrs`, `_augment_node_trace`). Still Phase A — do **not** start `glea-service`, audit-event contracts, the RabbitMQ consumer, egress enforcement, rationale, tiles, or the frontend.

## Item 1 — Span-wrap every node factory (no gaps in the trace tree; lineage across MI/callActivity/compensation)

Today only `task_runner.make_task_node` is instrumented, so any process using other node types has holes in its trace tree and, worse, a producer that is an uninstrumented node leaves its consumers' lineage links dangling. Wrap the remaining factories, reusing the shared helpers (factor out the common span+lineage logic from `make_task_node` so it is not duplicated).

**Artifact-producing executor nodes — full instrumentation (span + producer recording + input-artifact links), exactly like `make_task_node`:**
- `multi_instance.py`: `make_mi_iteration_node`, `make_sequential_mi_node` — each iteration is a span; record its produced (index-scoped) artifact's span context; attach input links from the iteration's `input_map`.
- `multi_instance.py`: `make_mi_join_node` — **this is the important lineage subtlety.** The join produces the aggregated artifact, so it must (a) be a span, (b) record *itself* as the producer of the aggregated artifact, and (c) link to the per-iteration producer spans it aggregates, so lineage `N iterations → join → downstream` is navigable end-to-end.
- `call_activity.py`: `make_map_node` — span + producer recording + input links for the mapped (call-activity) execution.
- `compensation.py`: the compensation handler node(s) that execute an undo side effect — span + structural attrs. (A compensation is a real side-effectful execution and belongs in the trace; `actor_kind` stays `capability`.)

**Control / routing nodes — lightweight span only (structural name + `element_id`, no lineage links, no producer recording):**
- `compiler.py`: `_make_end_node`, `_timer_catch_node`, `_event_gateway_node`, `_scope_entry_node`, `_passthrough_node`, `_failure_node`, and `multi_instance.make_mi_dispatch_node`. These don't produce consumable artifacts — they just need a span so the tree has no gaps. Keep `record_exception=False`/`set_status_on_exception=False` (as `node_span` already does) so a `interrupt()`/boundary divert never looks like a failure.
- `compiler.py`: `_message_node` — if the message binding commits a **typed artifact** (not a pure signal), treat it as artifact-producing (record its producer span so downstream consumers can link); if it's a pure signal, a lightweight span is enough.

Every wrapped node parents to the instance root via `restore_instance_context(state.trace["otel"])` and threads `execution_mode`/`simulation` like `make_task_node`. All attributes stay in the `amendia.*` structural namespace — **no domain terms** (review gate). Purely additive: no change to what any node computes, commits, routes to, or returns; `state.trace` remains optional (absent → fresh trace, never a crash).

## Item 2 — Bootstrap telemetry in the real cross-process capability-worker

The nemoclaw sandbox-correlation criterion is currently proven only against the **in-process fake** (which exports via agent-runtime's provider). The real out-of-process worker (`worker/main.py` + `worker/consumer.py`) has no TracerProvider of its own, so in the production nemoclaw profile its execution spans are never exported and the sandbox span never unifies into the instance trace.

- Call `configure_telemetry(service_name="agent-runtime-worker", ...)` at worker startup (`worker/main.py`), before the consumer loop, so the worker installs its own provider. Endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT` as everywhere else; **absent ⇒ disabled, never a crash.**
- Confirm the worker reads the node **traceparent** handed down through the spec (the `ExecutionContext.extras → spec → worker` path you built) and parents its execution span to it via `emit_linked_span(traceparent, ...)`, returning the real OTLP trace id that replaces the synthetic marker. If any leg of that hand-down is missing on the real path (only wired for the fake), complete it.
- Wire `OTEL_EXPORTER_OTLP_ENDPOINT` into the worker's deploy (its Dockerfile/compose service/env) so it points at the same Collector as everything else.

## Constraints (unchanged from Phase A)

- Domain-neutral: no pack/domain term in any span name, attribute, or resource. Review gate.
- Additive & side-effect-free w.r.t. graph execution; `state.trace` optional; no OTLP endpoint ⇒ telemetry disabled cleanly.
- Out of scope: `glea-service`, audit-event contracts, RabbitMQ audit consumer, egress enforcement, rationale capture, metrics/tiles, frontend (Phases B–E).
- Keep tests green; the two known wire-stub failures stay untouched.

## Acceptance / exit criteria

1. A process that exercises **multi-instance**, **call-activity**, and **compensation** paths produces, in ClickHouse `otel_traces`, **one trace with no orphan or gap spans** — every graph node appears as a span under the instance root. Add/extend a test that runs such a graph (reuse an existing MI/callActivity/compensation fixture) and asserts the tree is complete.
2. **MI lineage is navigable end-to-end:** the aggregated-artifact consumer links (transitively) back through the join span to the per-iteration producer spans. Asserted in the test.
3. The **real cross-process worker** (nemoclaw profile, not the in-process fake) exports its execution span, parented to the node span, unified into the instance trace — verified against ClickHouse (or an equivalent worker-provider export assertion where a live broker isn't available in CI).
4. No domain term in any emitted span/attribute; full existing suites pass (except the two known wire-stub failures); a Collector-down run still completes normally.

## Working agreement

Supervised: you (CC) write the code; propose the shared-helper refactor (the common span+lineage core extracted from `make_task_node`) before applying it across the factories. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).
