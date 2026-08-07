# app/logging_conf.py
"""Structured logging setup.

Emits key=value lines to stdout and enriches every record with the current
``request_id`` and ``trigger_id`` when they have been bound to the ambient
context (see ``middleware.request_id`` and the generate route).
"""
from __future__ import annotations

import contextvars
import logging
import sys

# Ambient context, bound per-request / per-trigger and read by the log filter.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
trigger_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trigger_id", default="-")


class ContextFilter(logging.Filter):
    """Attach ambient context vars to each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.trigger_id = trigger_id_ctx.get()
        return True


LOG_FORMAT = (
    "%(asctime)s level=%(levelname)s logger=%(name)s "
    "request_id=%(request_id)s trigger_id=%(trigger_id)s msg=%(message)s"
)

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Idempotently configure the root logger."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    root.addHandler(handler)
    _configured = True
