# amendia_telemetry/tracing.py
"""Thin, pure helpers for the instance trace (ADR-058 §5). No engine imports.

The pattern (so a trace survives HITL waits and crash-recovery across process restarts):

  * ``start_instance_trace`` emits the instance **root span** and returns a JSON-serializable
    context dict. The engine persists it in ``state.trace["otel"]`` (checkpointed), so it
    outlives the process.
  * On every node execution ``restore_instance_context`` rebuilds a parent ``Context`` from that
    dict and ``node_span`` opens a child span under it — so all node spans re-parent to the one
    root, even days later.
  * **Lineage rides on span links:** a node links to the span(s) that produced its input
    artifacts (``link_to``), recording each producer's context (``span_context_dict``) so
    consumers can find it.

Everything degrades silently: if telemetry was never configured the tracer is a no-op and the
context dicts are invalid — callers treat an absent/invalid context as "start a fresh trace,
never crash" (mirrors ADR-017's ``exec_meta``-omitted-in-native discipline).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from opentelemetry import trace
from opentelemetry.trace import Link, NonRecordingSpan, SpanContext, TraceFlags
from opentelemetry.trace.propagation import set_span_in_context

_TRACER_NAME = "amendia.instance"


def _tracer():
    return trace.get_tracer(_TRACER_NAME)


# --------------------------------------------------------------------------- #
# (de)serialization of a span context — what gets persisted into state.trace
# --------------------------------------------------------------------------- #
def span_context_dict(ctx: SpanContext) -> Dict[str, Any]:
    """Serialize a SpanContext to a JSON-safe dict (hex ids)."""
    return {
        "trace_id": trace.format_trace_id(ctx.trace_id),
        "span_id": trace.format_span_id(ctx.span_id),
        "trace_flags": int(ctx.trace_flags),
    }


def _is_valid_dict(d: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(d, dict) or "trace_id" not in d or "span_id" not in d:
        return False
    try:
        return int(d["trace_id"], 16) != 0 and int(d["span_id"], 16) != 0
    except (ValueError, TypeError):
        return False


def _span_context_from_dict(d: Dict[str, Any]) -> SpanContext:
    return SpanContext(
        trace_id=int(d["trace_id"], 16),
        span_id=int(d["span_id"], 16),
        is_remote=True,
        trace_flags=TraceFlags(int(d.get("trace_flags", TraceFlags.SAMPLED))),
    )


# --------------------------------------------------------------------------- #
# root span
# --------------------------------------------------------------------------- #
def start_instance_trace(correlation_id: str, *, attrs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Emit the instance root span and return its serializable context dict for ``state.trace``.

    The span is short (it anchors the trace id + a root parent span id); node spans re-parent to
    it via ``restore_instance_context``. Returns an empty dict when telemetry is off / the context
    is invalid, so ``state.trace["otel"]`` is simply absent and nodes start a fresh trace.
    """
    span = _tracer().start_span("instance", attributes={k: v for k, v in (attrs or {}).items() if v is not None})
    ctx = span.get_span_context()
    span.end()
    d = span_context_dict(ctx)
    return d if _is_valid_dict(d) else {}


def restore_instance_context(otel_ctx: Optional[Dict[str, Any]]):
    """Rebuild a parent ``Context`` from a persisted root-span dict, or ``None`` when absent/invalid."""
    if not _is_valid_dict(otel_ctx):
        return None
    parent = NonRecordingSpan(_span_context_from_dict(otel_ctx))  # type: ignore[arg-type]
    return set_span_in_context(parent)


# --------------------------------------------------------------------------- #
# node span + lineage links
# --------------------------------------------------------------------------- #
def link_to(span_ctx_dicts: Iterable[Optional[Dict[str, Any]]]) -> List[Link]:
    """Build span ``Link``s from persisted producer-span context dicts (lineage). Invalid/absent skipped."""
    links: List[Link] = []
    for d in span_ctx_dicts:
        if _is_valid_dict(d):
            links.append(Link(_span_context_from_dict(d)))  # type: ignore[arg-type]
    return links


@contextmanager
def node_span(
    root_ctx,
    name: str,
    *,
    links: Optional[List[Link]] = None,
    attrs: Optional[Dict[str, Any]] = None,
):
    """Open a node span parented to the instance root (``root_ctx`` from ``restore_instance_context``).

    Yields the live span so the caller can add attributes/links known only after execution (e.g. a
    sandbox ``exec_meta`` trace id). Set-as-current so a delegated sandbox execution can propagate
    the node as its parent via ``current_traceparent()``.
    """
    clean = {k: v for k, v in (attrs or {}).items() if v is not None}
    # LangGraph's ``interrupt()`` raises a control-flow exception to pause at a HITL gate — that is
    # not an error, so we do NOT auto-record exceptions / set ERROR status on the node span (a paused
    # gate must not look like a failure in the trace). Purely additive to graph control flow.
    with _tracer().start_as_current_span(
        name,
        context=root_ctx,
        links=links or [],
        attributes=clean,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


def add_exec_meta_link(span, otlp_trace_id: Optional[str]) -> None:
    """Best-effort: correlate a sandbox execution (its own OTLP trace) to this node span.

    Sets an attribute always; adds a span link when the SDK build supports ``add_link``. The
    ``otlp_trace_id`` may be a full traceparent, a bare trace id, or a synthetic marker — we set
    the attribute regardless and only link when it parses as a real 128-bit trace id."""
    if not otlp_trace_id:
        return
    from .conventions import EXEC_META_TRACE_ID

    span.set_attribute(EXEC_META_TRACE_ID, str(otlp_trace_id))
    add_link = getattr(span, "add_link", None)
    if not callable(add_link):
        return
    try:
        tid = int(str(otlp_trace_id).replace("-", "")[:32], 16)
        if tid != 0:
            add_link(SpanContext(trace_id=tid, span_id=0, is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED)))
    except (ValueError, TypeError):
        pass  # synthetic / non-hex marker — the attribute already records it


def emit_linked_span(traceparent: Optional[str], name: str, *, attrs: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Emit a short span parented to a W3C ``traceparent`` and return its trace id (hex).

    Used by the sandbox side (nemoclaw) so a delegated capability execution becomes a real span that
    **unifies into the instance trace** (child of the node span whose traceparent was handed down),
    instead of an opaque synthetic id. Returns ``None`` when telemetry is off or no parent is given.
    """
    if not traceparent:
        return None
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        parent = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    except Exception:  # noqa: BLE001
        parent = None
    span = _tracer().start_span(
        name, context=parent, attributes={k: v for k, v in (attrs or {}).items() if v is not None}
    )
    ctx = span.get_span_context()
    span.end()
    return trace.format_trace_id(ctx.trace_id) if ctx.is_valid else None


def bound_rationale(text: Optional[str]) -> Optional[str]:
    """ADR-058 Phase C: normalize + length-bound a captured agent rationale (the model's reasoning
    prose). Returns None for empty/whitespace input (a capability with no reasoning has no rationale —
    never fabricate one). Truncates to ``RATIONALE_MAX_CHARS`` with an ellipsis so a span attribute /
    audit row never grows unbounded. Domain-neutral **key**; the value is model content (not scrubbed)."""
    from .conventions import RATIONALE_MAX_CHARS

    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    if len(s) > RATIONALE_MAX_CHARS:
        return s[: RATIONALE_MAX_CHARS - 1].rstrip() + "…"
    return s


def current_traceparent() -> Optional[str]:
    """W3C ``traceparent`` of the currently-active span (the node span), for handing to a sandbox
    so its execution span parents to this node. ``None`` when there is no valid current span."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return f"00-{trace.format_trace_id(ctx.trace_id)}-{trace.format_span_id(ctx.span_id)}-{int(ctx.trace_flags):02x}"
