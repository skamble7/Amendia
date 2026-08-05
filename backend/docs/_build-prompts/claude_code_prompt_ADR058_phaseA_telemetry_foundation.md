# CC Prompt — ADR-058 Phase A: Telemetry foundation (OTel + ClickHouse, instance tracing with lineage links)

**Read first:** `backend/docs/adr/ADR-058-glea-observability-on-otel-and-clickhouse.md` and `backend/docs/engineering/amendia_glea_otel_implementation_plan.md`. This prompt implements **Phase A only** (the foundation). Phases B–E (the `glea-service`, audit-event contracts + RabbitMQ consumer, rationale, tiles, frontend) are explicitly out of scope here.

## Goal

Stand up the telemetry backbone and make every process instance emit **one coherent distributed trace** — spanning engine node executions and sandbox executions — with **lineage links between artifact producers and consumers**, persisted to **ClickHouse**, in **both** `native` and `nemoclaw` execution modes. No audit-event consumer, no Prometheus/Grafana/Loki.

## Scope

### 1. New shared package `amendia_telemetry` (sibling to `amendia_contracts`)

- OTel SDK bootstrap for **traces** (and a logs provider skeleton; audit-event emission is Phase B). A single `configure_telemetry(service_name, settings)` that sets a `TracerProvider` with resource attributes (`service.name`, and Amendia resource attrs), an **OTLP exporter** to the Collector, and a batch span processor. No-op / console exporter when the OTLP endpoint is unset so tests and local runs never hard-depend on the Collector.
- **Semantic conventions** as constants — structural only, no domain terms: `amendia.correlation_id`, `amendia.process_instance_id`, `amendia.pack_key`, `amendia.pack_version`, `amendia.element_id`, `amendia.actor`, `amendia.actor_kind`, `amendia.role`, `amendia.artifact_key`, `amendia.schema_ref`, `amendia.execution_mode`, `amendia.simulation`. (Decision/egress/rationale attrs are defined but populated in later phases.)
- Helpers: `start_instance_trace(...)` (creates the instance root span, returns a serializable span-context dict), `restore_instance_context(trace_state)` (rebuilds a context from the persisted dict), `node_span(root_ctx, element_id, actor, actor_kind, **attrs)` (child span parented to the root), and `link_to(span_contexts)` (produce span links). Keep helpers thin and pure; no engine imports.
- Config: an `OTEL_EXPORTER_OTLP_ENDPOINT` (or reuse existing settings pattern) per service; **absent → disabled**, never a crash.

### 2. Instrument `agent-runtime` (the deep path)

- **Persist the instance root span context in `state.trace`.** On instance start (`engine.py` where `initial_state`/`trace` is built — today `trace = {"correlation_id": ..., "causation_id": None}`), create the root span via `start_instance_trace` and store its serializable context under `state.trace` (e.g. `state.trace["otel"] = {trace_id, span_id, trace_flags}`) **without** disturbing the existing `correlation_id`/`causation_id` keys. On **resume** and on **crash-recovery re-invoke**, rebuild the context from `state.trace["otel"]` so new node spans re-parent to the same root. If the key is absent (old instances), start a fresh trace — never crash.
- **Wrap each node execution** in `task_runner.py` in a `node_span` parented to the restored root, tagged with `element_id`, `actor`, `actor_kind` (`capability`|`human`|`timer`), `execution_mode`, `simulation`, and the primary `artifact_key`/`schema_ref`. The span wraps existing logic; it must be additive and side-effect-free — no change to what the node computes, commits, or returns.
- **Lineage via span links.** When a node commits an artifact, record that artifact's producing span context into state (e.g. `state.trace["artifact_spans"][artifact_key] = ctx`, a merge-dict so concurrent branches don't clobber). When a node consumes inputs, read the producer contexts for the artifacts named in its `input_map` and attach them as **span links** on the node span. Result: the dataflow graph is navigable in the trace.
- **Native + nemoclaw parity.** In `native`, the in-process SDK produces the node span directly (this alone closes the "native has no trace" gap). In `nemoclaw`, the sandbox already emits OTLP with an `exec_meta` trace id (ADR-017); ensure the sandbox span is correlated to the node span — pass the node span context down so the sandbox span is a child (or, if that's not feasible via the current OpenShell contract, attach the sandbox trace id as a span link + `exec_meta` attribute). Point the sandbox/OpenShell OTLP exporter at the **same** Collector endpoint.

### 3. Bootstrap the other services (shallow)

`process-registry`, `platform/identity`, `platform/notification-service`, `ingestor`, `platform/config-forge-service`: call `configure_telemetry` at startup so their spans (HTTP handlers, etc.) flow to the Collector. Deep per-action instrumentation is later phases — Phase A is bootstrap + auto-instrumentation of the web framework only.

### 4. Infra (compose + reference configs)

- Add **OTel Collector** and **ClickHouse** to the compose stack with reference configs. Collector receives OTLP (gRPC + HTTP) and exports **traces and logs to ClickHouse** via the `clickhouseexporter` (otel-collector-contrib). Create the ClickHouse schema (`otel_traces`, `otel_logs`) — use the exporter's standard schema. **Do not** add Prometheus, Grafana, or Loki.
- Wire service + sandbox OTLP endpoints to the Collector via env/config. Keep everything working when the Collector is down (exporter failures must not break request handling).

## Constraints (hard)

- **Domain-neutral:** no pack/domain term in any attribute, span name, or resource — span names are structural (e.g. the `element_id`/`actor`), attributes are the `amendia.*` set above. This is a review gate.
- **Additive & side-effect-free:** instrumentation must not change graph control flow, node outputs, commit behavior, or existing API responses. The only new state is `state.trace["otel"]` / `state.trace["artifact_spans"]`, both optional (absent → new trace, never a crash) — mirror the ADR-017 native-parity discipline.
- **No new hard dependency at runtime:** OTLP endpoint unset ⇒ telemetry disabled cleanly.
- Do **not** implement the `glea-service`, audit-event contracts, RabbitMQ audit consumer, egress enforcement, rationale capture, metrics/tiles, or frontend — those are Phases B–E.
- Keep existing tests green. The two pre-existing wire-stub failures (`test_assess_beneficiary_produces_all_three_verdicts`, `test_sdk_tools_list_and_structured_call`) are known/unrelated — do not chase them here.

## Acceptance / exit criteria

1. A full `wire-repair` run in **`native`** mode produces, in ClickHouse `otel_traces`, **one trace** for the instance whose spans form the node execution tree, with **span links** from each consuming node to the spans that produced its `input_map` artifacts.
2. The same run in **`nemoclaw`** mode produces a trace where the sandbox execution span is correlated (child or linked) to the corresponding node span, via the same Collector.
3. A **resumed** instance (HITL decide → resume) and a **recovered** instance (restart mid-run) continue the **same** trace — node spans after resume re-parent to the original root from `state.trace`.
4. With the Collector stopped, a run still completes normally (telemetry disabled/dropped, no request errors).
5. No domain term appears in any emitted span/attribute; existing test suites (except the two known wire-stub failures) pass.

## Working agreement

Supervised build: you (CC) write the code; propose the concrete file-level changes and the `amendia_telemetry` package layout before large edits. **Do not `git add`/commit/push** — the operator handles commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).
