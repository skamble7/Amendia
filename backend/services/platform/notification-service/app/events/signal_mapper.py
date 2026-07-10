# app/events/signal_mapper.py
"""Map a raw broker event → a **thin invalidation signal** for the browser.

This is the security boundary of the notification-service. A signal carries ONLY
whitelisted id/label fields — never payload data (no ``decision``, ``comment``,
``edits``, ``trace``, ``reason``, ``detail``, capability outputs, …). The browser
uses the signal only to decide which TanStack Query keys to invalidate; the actual
(authorized) data is then re-fetched through the role-guarded REST endpoints. So
even though the SSE stream is broadcast to every authenticated operator, it can
never leak sensitive data.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from amendia_common.events import (
    DISPATCH_ACCEPTED,
    DISPATCH_REJECTED,
    EXCEPTION_DISPATCHED,
    EXCEPTION_RAISED,
    HITL_TASK_CREATED,
    HITL_TASK_DECIDED,
    PROCESS_COMPLETED,
    PROCESS_FAILED,
)

# Events we relay to the UI. Anything else on the exchange is ignored.
KNOWN_EVENTS = frozenset({
    EXCEPTION_RAISED,
    EXCEPTION_DISPATCHED,
    DISPATCH_ACCEPTED,
    DISPATCH_REJECTED,
    HITL_TASK_CREATED,
    HITL_TASK_DECIDED,
    PROCESS_COMPLETED,
    PROCESS_FAILED,
})

# The ONLY fields ever copied into a signal (ids + non-sensitive labels).
_ALLOWED_FIELDS = (
    "exception_id",
    "process_instance_id",
    "task_id",
    "element_id",
    "role",
    "outcome",
)


def event_type(routing_key: str) -> Optional[str]:
    """Extract the ``<event>`` segment of a ``<service>.<event>.<version>`` routing
    key. Event names contain no dots and the version is the last segment, so the
    event is always the second-to-last segment."""
    parts = routing_key.split(".")
    if len(parts) < 3:
        return None
    return parts[-2]


def to_signal(payload: Dict[str, Any], routing_key: str) -> Optional[Dict[str, Any]]:
    """Return a thin signal, or None if the event isn't one we relay."""
    etype = event_type(routing_key)
    if etype not in KNOWN_EVENTS:
        return None
    signal: Dict[str, Any] = {"type": etype}
    for field in _ALLOWED_FIELDS:
        value = payload.get(field)
        if value is not None:
            signal[field] = value
    return signal
