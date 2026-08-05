# tests/test_telemetry_tracing.py
"""ADR-058 Phase A — the instance trace: one trace per instance + input-artifact lineage links.

Drives a full native wire-repair (AC01) run with an in-memory span exporter attached and asserts:
  * every node span belongs to the ONE persisted instance root trace (survives HITL resume replays);
  * consuming nodes carry span *links* to the spans that produced their input artifacts (lineage);
  * node-span attributes are structural (`amendia.*`) only — the domain-neutrality review gate.

Native mode alone closes the "native has no trace" gap; the sandbox trace-id correlation is covered by
``test_sandboxed_executor``/``test_capability_worker_broker``.
"""
from __future__ import annotations

from opentelemetry import trace as _t
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from langgraph.checkpoint.memory import MemorySaver

from amendia_telemetry import configure_telemetry, conventions as C, start_instance_trace
from app.engine.compiler import compile_graph
from app.engine.state import initial_state
from app.engine.task_runner import IOSpec, NodeContext, _input_lineage_links
from tests._wire import drive, make_envelope
from tests.test_sandboxed_executor import _native_app


def _run_and_capture(thread_id: str, exception_id: str):
    # Ensure a real SDK TracerProvider (idempotent — a no-op if a prior test's create_app configured it),
    # then attach an in-memory exporter to capture this run's spans.
    configure_telemetry("test-agent-runtime")
    exporter = InMemorySpanExporter()
    provider = _t.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = _native_app()
    # Mirror engine.start: open the instance root span + persist its context into state.trace["otel"].
    otel = start_instance_trace(exception_id, attrs={C.CORRELATION_ID: exception_id})
    init = initial_state(
        envelope=make_envelope("AC01", exception_id=exception_id),
        trace={"correlation_id": exception_id, "otel": otel},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )
    result, _gates = drive(app, {"configurable": {"thread_id": thread_id}}, init)
    provider.force_flush()
    return result, otel, exporter.get_finished_spans()


def test_native_run_is_one_trace_with_lineage_links():
    result, otel, spans = _run_and_capture("t-otel-ac01", "EXC-OTEL-AC01")
    assert result["outcome"] == "End_Resolved"
    root_tid = int(otel["trace_id"], 16)

    node_spans = [s for s in spans if s.attributes and C.ELEMENT_ID in s.attributes]
    assert node_spans, "expected node spans carrying amendia.element_id"

    # Criterion 1 + 3: every node span (including post-resume re-executions) re-parents to the ONE root.
    assert all(s.context.trace_id == root_tid for s in node_spans), "node spans must share the instance root trace"

    # Lineage: consuming nodes link to the spans that produced their input artifacts, in the same trace.
    linked = [s for s in node_spans if s.links]
    assert linked, "expected input-artifact span links on consuming nodes"
    assert all(link.context.trace_id == root_tid for s in linked for link in s.links)

    # Domain-neutrality gate: node-span attribute keys are structural amendia.* only.
    assert all(str(k).startswith("amendia.") for s in node_spans for k in s.attributes)
    assert node_spans[0].attributes[C.EXECUTION_MODE] == "native"
    assert C.SIMULATION in node_spans[0].attributes


def test_reasoning_nodes_carry_bounded_rationale_mcp_nodes_do_not():
    # ADR-058 Phase C: the llm (reasoning) capabilities carry a bounded amendia.rationale on their span
    # (and in actor_log meta); plain MCP-tool nodes carry none (no fabrication).
    result, _otel, spans = _run_and_capture("t-otel-rat", "EXC-OTEL-RAT")
    assert result["outcome"] == "End_Resolved"
    node_spans = [s for s in spans if s.attributes and C.ELEMENT_ID in s.attributes]

    def spans_for(element_id):
        return [s for s in node_spans if s.attributes.get(C.ELEMENT_ID) == element_id]

    # Task_RecordResolution + Task_DraftRepair are `llm` (stub inference) → rationale present + bounded.
    llm_spans = spans_for("Task_RecordResolution") + spans_for("Task_DraftRepair")
    assert llm_spans, "expected the llm capability node spans"
    rat = [s for s in llm_spans if C.RATIONALE in s.attributes]
    assert rat, "an llm reasoning node must carry amendia.rationale"
    for s in rat:
        val = s.attributes[C.RATIONALE]
        assert isinstance(val, str) and 0 < len(val) <= 1200

    # Task_EnrichPayment / Task_SanctionsRescreen are plain MCP tools → NO rationale (never fabricated).
    for mcp_el in ("Task_EnrichPayment", "Task_SanctionsRescreen"):
        for s in spans_for(mcp_el):
            assert C.RATIONALE not in s.attributes, f"{mcp_el} must not carry a fabricated rationale"

    # And the rationale rides the actor_log entry meta (checkpoint surface), not only the span.
    metas = [e.get("exec_meta", {}) for e in result["actor_log"]
             if e.get("element_id") in ("Task_RecordResolution", "Task_DraftRepair")]
    assert any(isinstance(m, dict) and m.get("rationale") for m in metas)


# --------------------------------------------------------------------------- #
# ADR-058 Phase A closeout — full node-factory span coverage: an MI run is ONE trace with no
# orphan/gap spans, and its aggregate lineage fans back out to every parallel iteration.
# --------------------------------------------------------------------------- #
def _capture_provider():
    """Idempotent SDK provider + a fresh in-memory exporter attached to it."""
    configure_telemetry("test-agent-runtime")
    exporter = InMemorySpanExporter()
    provider = _t.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_multi_instance_run_is_one_trace_with_navigable_lineage():
    # Reuse the real compiler + seed-bundle MI harness (a task turned parallel multi-instance).
    from tests.test_multi_instance import MIHybridExecutor, _mi_bundle, _mi_xml

    provider, exporter = _capture_provider()

    host = "Task_RecordResolution"
    bundle = _mi_bundle(_mi_xml(sequential=False, cardinality=2))
    executor = MIHybridExecutor("cap.payment.record_resolution")
    app = compile_graph(bundle, executor, simulation=True, checkpointer=MemorySaver(),
                        profile="common_executable")

    otel = start_instance_trace("EXC-MI-OTEL", attrs={C.CORRELATION_ID: "EXC-MI-OTEL"})
    init = initial_state(
        envelope=make_envelope("AC01", exception_id="EXC-MI-OTEL"),
        trace={"correlation_id": "EXC-MI-OTEL", "otel": otel},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )
    final, _gates = drive(app, {"configurable": {"thread_id": "mi-otel"}}, init)
    provider.force_flush()
    spans = exporter.get_finished_spans()

    assert final["outcome"] == "End_Resolved"
    root_tid = int(otel["trace_id"], 16)

    # Criterion 1: NO orphan/gap spans. Every emitted node span — task, MI dispatch/iteration/join,
    # and the control nodes (end) — re-parents to the ONE instance root trace. A gap (an un-wrapped
    # factory) would surface here as a span on a different trace id.
    node_spans = [s for s in spans if s.attributes and C.ELEMENT_ID in s.attributes]
    assert node_spans, "expected node spans carrying amendia.element_id"
    assert all(s.context.trace_id == root_tid for s in node_spans), \
        "every node/control span must share the instance root trace (no orphan/gap spans)"

    # The MI subgraph produced its own spans: a dispatch, N iterations, one join.
    iter_spans = [s for s in node_spans if s.name == f"{host}__mi_iter"]
    join_spans = [s for s in node_spans if s.name == f"{host}__mi_join"]
    dispatch_spans = [s for s in node_spans if s.name == f"{host}__mi_dispatch"]
    assert len(iter_spans) == 2, "one span per parallel iteration (cardinality=2)"
    assert len(join_spans) == 1 and dispatch_spans, "join barrier + dispatch present in the tree"

    # Criterion 2 (navigable MI lineage, half 1): the join links BACK to every per-iteration producer
    # span, so the aggregate's provenance fans out to the N iterations that produced it.
    join = join_spans[0]
    iter_span_ids = {s.context.span_id for s in iter_spans}
    join_link_ids = {link.context.span_id for link in (join.links or [])}
    assert iter_span_ids <= join_link_ids, "join must link to every per-iteration producer span"
    assert all(link.context.trace_id == root_tid for link in join.links)

    # Criterion 2 (navigable MI lineage, half 2): a downstream node CONSUMING the aggregated artifact
    # resolves a span link to the join — exercised through the exact `_input_lineage_links` path a real
    # consumer uses (the seed routes the MI host straight to End, so we drive that path directly).
    consumer_ctx = NodeContext(
        element_id="Downstream", element_kind="serviceTask", hitl_mode="none", role=None,
        executor_type="capability", inputs=[IOSpec(name="resolution", schema_ref="art.x@1.0.0")])
    consumer_link_ids = {link.context.span_id for link in _input_lineage_links(consumer_ctx, final)}
    assert join.context.span_id in consumer_link_ids, \
        "a consumer of the aggregated artifact must link to the join (consumer → join → iterations)"


def test_cross_process_worker_span_unifies_into_instance_trace():
    """ADR-058 Phase A closeout, Item 2: the out-of-process capability-worker parents its
    ``sandbox.capability`` span to the node span's handed-down W3C traceparent, so a cross-process
    execution lands in the ONE instance trace — not a synthetic/orphan id. Exercised through the same
    ``worker_runner.run_job`` code the real RabbitMQ worker runs (here over the in-memory transport)."""
    from tests.test_capability_worker_broker import _broker_graph

    provider, _exporter = _capture_provider()

    otel = start_instance_trace("EXC-BRK-OTEL", attrs={C.CORRELATION_ID: "EXC-BRK-OTEL"})
    root_hex = otel["trace_id"]
    init = initial_state(
        envelope=make_envelope("AC01", exception_id="EXC-BRK-OTEL"),
        trace={"correlation_id": "EXC-BRK-OTEL", "otel": otel},
        pack={"pack_key": "wire-repair-standard", "pack_version": "1.0.0"},
    )
    result, _gates = drive(_broker_graph(), {"configurable": {"thread_id": "brk-otel"}}, init)
    provider.force_flush()

    assert result["outcome"] == "End_Resolved"
    cap_entries = [e for e in result["actor_log"] if e["kind"] == "capability" and "exec_meta" in e]
    worker_trace_ids = {e["element_id"]: e["exec_meta"]["otlp_trace_id"] for e in cap_entries
                        if e.get("exec_meta", {}).get("otlp_trace_id")}
    assert worker_trace_ids, "expected worker-emitted OTLP trace ids in the capability actor_log"
    # Every cross-process worker span carries the SAME trace id as the persisted instance root — it was
    # parented (via emit_linked_span) to the node span, which is a child of the instance root.
    assert all(t == root_hex for t in worker_trace_ids.values()), \
        "worker sandbox.capability spans must unify into the instance root trace"
