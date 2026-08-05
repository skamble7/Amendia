# amendia_telemetry — OTel bootstrap + domain-neutral conventions + instance-trace helpers (ADR-058).
from . import conventions
from .bootstrap import configure_telemetry, get_tracer
from .tracing import (
    add_exec_meta_link,
    bound_rationale,
    current_traceparent,
    emit_linked_span,
    link_to,
    node_span,
    restore_instance_context,
    span_context_dict,
    start_instance_trace,
)

__all__ = [
    "conventions",
    "configure_telemetry",
    "get_tracer",
    "start_instance_trace",
    "restore_instance_context",
    "node_span",
    "link_to",
    "add_exec_meta_link",
    "current_traceparent",
    "emit_linked_span",
    "span_context_dict",
    "bound_rationale",
]
